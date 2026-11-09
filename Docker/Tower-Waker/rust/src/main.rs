//! Tower-Waker: Wake-on-LAN gate + manual LAN wake page for tower (Traefik forwardAuth on fastpi :9002).
#![forbid(unsafe_code)]

mod web;
mod wol;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use tokio::net::{TcpListener, TcpStream};
use web::{log, py_int, qs_first, take_chars, Req, Resp};

const PROBE_TIMEOUT: Duration = Duration::from_secs(1);
const SSH_PORT: u16 = 22;

const WAKE_PAGE: &str = include_str!("pages/wake.html");
const NC_PAGE: &str = include_str!("pages/nc.html");
const NC_SIGNIN_PAGE: &str = include_str!("pages/nc-signin.html");
const WAKING_PAGE: &str = include_str!("pages/waking.html");
const NC_COOKIES: [&str; 4] = ["nc_session_id=", "nc_token=", "nc_username=", "oc_sessionpassphrase="];

struct App {
    mac: [u8; 6],
    mac_str: String,
    broadcast: String,
    probe_host: String,
    probe_port: u16,
    retry_interval: Duration,
    retry_window: Duration,
    page: String,
    page_auto: String,
    nc_page: String,
    campaign: AtomicBool,
}

fn env_or(k: &str, d: &str) -> String {
    std::env::var(k).unwrap_or_else(|_| d.to_string())
}

fn env_int(k: &str, d: &str) -> i64 {
    let v = env_or(k, d);
    py_int(&v).unwrap_or_else(|| fail(&format!("invalid literal for int() with base 10: '{v}' ({k})")))
}

fn fail(msg: &str) -> ! {
    eprintln!("{msg}");
    std::process::exit(1);
}

async fn is_up(host: &str, port: u16) -> bool {
    matches!(tokio::time::timeout(PROBE_TIMEOUT, TcpStream::connect((host, port))).await, Ok(Ok(_)))
}

impl App {
    fn send_wol(&self) -> std::io::Result<()> {
        wol::send(&self.mac, &self.broadcast)
    }

    /// Send a packet now (error = not sent), then resend in one background campaign until tower answers.
    fn wake(self: &Arc<Self>) -> std::io::Result<()> {
        self.send_wol()?;
        if self.campaign.swap(true, Ordering::SeqCst) {
            return Ok(());
        }
        let app = self.clone();
        tokio::spawn(async move {
            let deadline = Instant::now() + app.retry_window;
            while Instant::now() < deadline {
                tokio::time::sleep(app.retry_interval).await;
                if is_up(&app.probe_host, app.probe_port).await {
                    break;
                }
                let _ = app.send_wol();
            }
            app.campaign.store(false, Ordering::SeqCst);
        });
        Ok(())
    }

    fn wake_in_progress(&self) -> bool {
        self.campaign.load(Ordering::SeqCst)
    }

    async fn handle(self: Arc<Self>, r: Req) -> Resp {
        match r.route().as_str() {
            "/" => Resp::html(200, self.page.clone()),
            "/wol" => Resp::html(200, self.page_auto.clone()),
            "/status" | "/nc/status" => status_json(is_up(&self.probe_host, self.probe_port).await),
            "/wake" => self.manual_wake(&r, None),
            "/nc/wake" => {
                let user = take_chars(r.header("X-Authentik-Username").filter(|v| !v.is_empty()).unwrap_or("?"), 64).to_string();
                self.manual_wake(&r, Some(user))
            }
            "/history" => Resp::json(503, r#"{"error": "history key not installed"}"#),
            "/gate" => self.gate(&r).await,
            "/nc" => Resp::html(200, self.nc_page.clone()),
            _ => Resp::not_found(),
        }
    }

    fn manual_wake(self: &Arc<Self>, r: &Req, nc_user: Option<String>) -> Resp {
        if r.method != "POST" {
            return Resp::json(405, r#"{"error": "POST only"}"#);
        }
        if !wake_request_allowed(r) {
            return Resp::json(403, r#"{"error": "needs X-Wake: 1 from this origin"}"#);
        }
        let sent = match self.wake() {
            Ok(()) => {
                let msg = match &nc_user {
                    Some(u) => format!("nc wake by {u} -> sent WoL to {} via {}", self.mac_str, self.broadcast),
                    None => format!("manual wake -> sent WoL to {} via {}", self.mac_str, self.broadcast),
                };
                log(&r.peer, &msg);
                true
            }
            Err(e) => {
                log(&r.peer, &format!("WoL send failed: {e}"));
                false
            }
        };
        Resp::json(200, if sent { r#"{"sent": true}"# } else { r#"{"sent": false}"# })
    }

    async fn gate(self: &Arc<Self>, r: &Req) -> Resp {
        let q = r.query();
        let port = qs_first(&q, "port")
            .and_then(|p| py_int(&p))
            .filter(|p| (1..=65535).contains(p))
            .map(|p| p as u16)
            .unwrap_or(self.probe_port);
        if qs_first(&q, "policy").as_deref() == Some("nextcloud") {
            return self.gate_nextcloud(r, port).await;
        }
        if is_up(&self.probe_host, port).await {
            return Resp::text(200, "");
        }
        match self.wake() {
            Ok(()) => log(&r.peer, &format!("tower down ({}:{port}) - sent WoL to {} via {}", self.probe_host, self.mac_str, self.broadcast)),
            Err(e) => log(&r.peer, &format!("WoL send failed: {e}")),
        }
        Resp::html(503, WAKING_PAGE).retry_after(5)
    }

    async fn gate_nextcloud(self: &Arc<Self>, r: &Req, port: u16) -> Resp {
        let up = is_up(&self.probe_host, port).await;
        let starting = !up && (self.wake_in_progress() || is_up(&self.probe_host, SSH_PORT).await);
        let decision = nextcloud_decision(up, starting, r);
        if decision == "pass" {
            return Resp::text(200, "");
        }
        let ip = take_chars(r.header("CF-Connecting-IP").filter(|v| !v.is_empty()).or(r.header("X-Forwarded-For").filter(|v| !v.is_empty())).unwrap_or("?"), 45);
        let uri = r.header("X-Forwarded-Uri").filter(|v| !v.is_empty()).unwrap_or("/");
        let path = take_chars(uri.split('?').next().unwrap_or(""), 120);
        let ua = take_chars(r.header("User-Agent").filter(|v| !v.is_empty()).unwrap_or("-"), 60);
        if decision == "wake" {
            match self.wake() {
                Ok(()) => log(&r.peer, &format!("tower down ({}:{port}) - sent WoL to {} via {} [nextcloud client {ip} {ua}]", self.probe_host, self.mac_str, self.broadcast)),
                Err(e) => log(&r.peer, &format!("WoL send failed: {e}")),
            }
        } else {
            log(&r.peer, &format!("nextcloud {decision} (no wake) {ip} {path} {ua}"));
        }
        match decision {
            "signin" => Resp::html(503, NC_SIGNIN_PAGE),
            "refuse" => Resp::new(503, "text/plain; charset=utf-8", "Nextcloud is asleep.\n"),
            _ => Resp::html(503, WAKING_PAGE).retry_after(5),
        }
    }
}

fn status_json(up: bool) -> Resp {
    Resp::json(200, if up { r#"{"up": true}"# } else { r#"{"up": false}"# })
}

/// Only positive evidence of a Nextcloud user wakes tower: Authorization, a Nextcloud client UA, or Nextcloud cookies.
fn is_nextcloud_client(r: &Req) -> bool {
    if !r.header_or("Authorization").trim().is_empty() {
        return true;
    }
    let ua = r.header_or("User-Agent").to_lowercase();
    if ua.contains("mirall") || ua.contains("nextcloud") {
        return true;
    }
    let cookie = r.header_or("Cookie").to_lowercase();
    NC_COOKIES.iter().any(|c| cookie.contains(c))
}

fn nextcloud_decision(up: bool, starting: bool, r: &Req) -> &'static str {
    if up {
        "pass"
    } else if starting {
        "starting"
    } else if is_nextcloud_client(r) {
        "wake"
    } else if r.header_or("Accept").to_lowercase().contains("text/html") {
        "signin"
    } else {
        "refuse"
    }
}

/// CSRF guard: a cross-site page cannot add X-Wake without a CORS preflight, which the waker never answers.
fn wake_request_allowed(r: &Req) -> bool {
    if r.header("X-Wake") != Some("1") {
        return false;
    }
    let Some(origin) = r.header("Origin") else { return true };
    let host = r.header_or("Host").to_lowercase();
    !host.is_empty() && origin_netloc(origin).to_lowercase() == host
}

/// `urlparse(origin).netloc`
fn origin_netloc(origin: &str) -> &str {
    let mut u = origin;
    if let Some(i) = u.find(':') {
        let scheme = &u[..i];
        if i > 0 && scheme.as_bytes()[0].is_ascii_alphabetic() && scheme.bytes().all(|b| b.is_ascii_alphanumeric() || b"+-.".contains(&b)) {
            u = &u[i + 1..];
        }
    }
    match u.strip_prefix("//") {
        Some(rest) => &rest[..rest.find(['/', '?', '#']).unwrap_or(rest.len())],
        None => "",
    }
}

fn read_version() -> String {
    let path = env_or("WAKER_VERSION_FILE", "/app/VERSION");
    match std::fs::read_to_string(path) {
        Ok(v) if !v.trim().is_empty() => v.trim().to_string(),
        _ => "dev".to_string(),
    }
}

fn main() {
    let port = env_int("WAKER_LISTEN_PORT", "9001");
    let port = u16::try_from(port).unwrap_or_else(|_| fail("WAKER_LISTEN_PORT out of range"));
    let bind = env_or("WAKER_BIND", "0.0.0.0");
    if std::env::args().nth(1).as_deref() == Some("--health") {
        std::process::exit(web::health_check(&bind, port));
    }
    let mac_str = env_or("TARGET_MAC", "");
    let probe_host = env_or("TARGET_PROBE_HOST", "");
    let missing: Vec<&str> = [("TARGET_MAC", &mac_str), ("TARGET_PROBE_HOST", &probe_host)]
        .iter()
        .filter(|(_, v)| v.is_empty())
        .map(|(k, _)| *k)
        .collect();
    if !missing.is_empty() {
        fail(&format!("missing required env: {}", missing.join(", ")));
    }
    let mac = wol::parse_mac(&mac_str).unwrap_or_else(|| fail(&format!("invalid MAC: '{mac_str}'")));
    let probe_port = u16::try_from(env_int("TARGET_PROBE_PORT", "22")).unwrap_or_else(|_| fail("TARGET_PROBE_PORT out of range"));
    let countdown = env_int("WAKE_COUNTDOWN", "60");
    let retry_interval = env_int("WAKE_RETRY_INTERVAL", "20").max(0) as u64;
    let retry_window = env_int("WAKE_RETRY_WINDOW", "300");
    let version = read_version();
    let page = |auto: &str| {
        WAKE_PAGE.replace("__COUNTDOWN__", &countdown.to_string()).replace("__AUTOWAKE__", auto).replace("__VERSION__", &version)
    };
    let app = Arc::new(App {
        mac,
        broadcast: env_or("TARGET_BROADCAST", "255.255.255.255"),
        probe_port,
        retry_interval: Duration::from_secs(retry_interval),
        retry_window: Duration::from_secs(retry_window.max(0) as u64),
        page: page("false"),
        page_auto: page("true"),
        nc_page: NC_PAGE
            .replace("__COUNTDOWN__", &countdown.to_string())
            .replace("__GIVEUP__", &(retry_window + 60).to_string())
            .replace("__VERSION__", &version),
        campaign: AtomicBool::new(false),
        mac_str,
        probe_host,
    });
    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap_or_else(|e| fail(&format!("runtime: {e}")));
    rt.block_on(async move {
        let listener = TcpListener::bind((bind.as_str(), port)).await.unwrap_or_else(|e| fail(&format!("bind {bind}:{port}: {e}")));
        println!(
            "tower-waker listening on {bind}:{port} - page=/ gate=/gate, wake {} via {}, probe {}:{}",
            app.mac_str, app.broadcast, app.probe_host, app.probe_port
        );
        let a = app.clone();
        tokio::select! {
            _ = web::serve(listener, move |r| a.clone().handle(r)) => {}
            _ = shutdown() => {}
        }
    });
}

async fn shutdown() {
    use tokio::signal::unix::{signal, SignalKind};
    let (Ok(mut term), Ok(mut int)) = (signal(SignalKind::terminate()), signal(SignalKind::interrupt())) else {
        return std::future::pending().await;
    };
    tokio::select! {
        _ = term.recv() => {}
        _ = int.recv() => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn req(h: &[(&str, &str)]) -> Req {
        Req::new("GET", "/gate", "127.0.0.1", h.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect())
    }

    #[test]
    fn decisions() {
        assert_eq!(nextcloud_decision(true, false, &req(&[])), "pass");
        assert_eq!(nextcloud_decision(false, true, &req(&[("Authorization", "x")])), "starting");
        assert_eq!(nextcloud_decision(false, false, &req(&[("Authorization", "  ")])), "refuse");
        assert_eq!(nextcloud_decision(false, false, &req(&[("User-Agent", "Mozilla mirall/3")])), "wake");
        assert_eq!(nextcloud_decision(false, false, &req(&[("Cookie", "OC_SessionPassphrase=1")])), "wake");
        assert_eq!(nextcloud_decision(false, false, &req(&[("Accept", "TEXT/HTML")])), "signin");
    }

    #[test]
    fn csrf() {
        assert!(!wake_request_allowed(&req(&[])));
        assert!(wake_request_allowed(&req(&[("X-Wake", "1")])));
        assert!(wake_request_allowed(&req(&[("X-Wake", "1"), ("Origin", "https://A.example"), ("Host", "a.example")])));
        assert!(!wake_request_allowed(&req(&[("X-Wake", "1"), ("Origin", "https://a.example.evil"), ("Host", "a.example")])));
        assert!(!wake_request_allowed(&req(&[("X-Wake", "1"), ("Origin", "null"), ("Host", "a.example")])));
        assert!(!wake_request_allowed(&req(&[("X-Wake", "1"), ("Origin", "https://a.example")])));
    }

    #[test]
    fn origin_netloc_like_urlparse() {
        assert_eq!(origin_netloc("https://h:1/x"), "h:1");
        assert_eq!(origin_netloc("h:1"), "");
        assert_eq!(origin_netloc("//h"), "h");
    }
}
