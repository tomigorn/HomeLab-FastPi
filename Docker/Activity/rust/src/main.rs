//! Activity: anonymous "who is watching / listening, what is downloading" for the homelab status page.
//! Pulls beefy only while Beefy-Waker /status says it is up (never wakes it), through the read-only activity-gate.
#![forbid(unsafe_code)]

mod api;
mod beefy;
mod client;
mod local;
mod state;
mod waker;

use std::collections::HashSet;
use std::convert::Infallible;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use http_body_util::Full;
use hyper::body::{Bytes, Incoming};
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper::{Request, Response};
use hyper_util::rt::{TokioIo, TokioTimer};
use serde::de::DeserializeOwned;
use tokio::net::TcpListener;
use tokio::sync::Semaphore;

use client::BaseUrl;
use state::{Local, Snapshot, WakerState};

const GATE_TIMEOUT: Duration = Duration::from_secs(3);
const SMALL: usize = 2 << 20;
const LARGE: usize = 4 << 20;
/// The last snapshot is rewritten when the downloads change, else at most this often.
const SAVE_EVERY: i64 = 600;
const MAX_CONNECTIONS: usize = 64;

fn now() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0)
}

fn now_ms() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
}

fn log(msg: &str) {
    println!("activity: {msg}");
}

fn fail(msg: &str) -> ! {
    eprintln!("activity: {msg}");
    std::process::exit(2)
}

fn env_or(k: &str, d: &str) -> String {
    std::env::var(k).ok().filter(|v| !v.trim().is_empty()).unwrap_or_else(|| d.to_string())
}

fn env_secs(k: &str, d: u64) -> Duration {
    Duration::from_secs(env_or(k, &d.to_string()).parse().unwrap_or_else(|_| fail(&format!("{k} must be whole seconds"))))
}

fn url(k: &str, d: &str) -> Option<BaseUrl> {
    let v = env_or(k, d);
    if v == "off" {
        return None;
    }
    Some(BaseUrl::parse(&v).unwrap_or_else(|| fail(&format!("{k} must be http://host[:port]"))))
}

struct App {
    snap: Mutex<Option<Snapshot>>,
    waker: Mutex<WakerState>,
    local: Mutex<Local>,
    access: api::Access,
    data: Option<PathBuf>,
    saved: Mutex<(i64, Option<Vec<state::Download>>)>,
    last_error: Mutex<String>,
}

impl App {
    fn view(&self) -> (state::View, Option<i64>) {
        let t = now();
        let snap = self.snap.lock().map(|s| s.clone()).unwrap_or(None);
        let waker = self.waker.lock().map(|w| *w).unwrap_or(WakerState::Unknown);
        let local = self.local.lock().map(|l| *l).unwrap_or_default();
        let age = snap.as_ref().map(|s| (t - s.at).max(0));
        (state::view(t, snap.as_ref(), waker, &local), age)
    }

    /// Logs a poll problem once per change, never a response body.
    fn note(&self, msg: &str) {
        if let Ok(mut last) = self.last_error.lock() {
            if *last != msg {
                if !msg.is_empty() {
                    log(msg);
                } else if !last.is_empty() {
                    log("beefy poll ok again");
                }
                *last = msg.to_string();
            }
        }
    }

    fn store(&self, s: Snapshot) {
        if let Some(path) = &self.data {
            if let Ok(mut saved) = self.saved.lock() {
                if saved.1.as_ref() != Some(&s.downloads) || s.at - saved.0 >= SAVE_EVERY {
                    match state::save(path, &s) {
                        Ok(()) => *saved = (s.at, Some(s.downloads.clone())),
                        Err(e) => log(&format!("saving {}: {e}", path.display())),
                    }
                }
            }
        }
        if let Ok(mut snap) = self.snap.lock() {
            *snap = Some(s);
        }
    }
}

async fn fetch<T: DeserializeOwned>(gate: &BaseUrl, path: &str, limit: usize) -> Result<T, String> {
    let body = client::get(gate, path, &[("accept", "application/json")], limit, GATE_TIMEOUT).await.map_err(|e| format!("{path}: {e}"))?;
    serde_json::from_slice(&body).map_err(|_| format!("{path}: unreadable answer"))
}

/// One poll through the gate, one attempt per path; raw answers are dropped as soon as they are grouped.
async fn poll_beefy(gate: &BaseUrl) -> Result<Snapshot, String> {
    let at = now();
    let sessions: Vec<beefy::Session> = fetch(gate, beefy::PATH_SESSIONS, SMALL).await?;
    let rs: beefy::RequestState = fetch(gate, beefy::PATH_REQUEST_STATE, SMALL).await?;
    let night: HashSet<String> = fetch::<beefy::NightWaiting>(gate, beefy::PATH_NIGHT_WAITING, SMALL).await.map(|n| n.ids()).unwrap_or_default();
    let radarr: beefy::Queue = fetch(gate, beefy::PATH_RADARR_QUEUE, LARGE).await?;
    let sonarr: beefy::Queue = fetch(gate, beefy::PATH_SONARR_QUEUE, LARGE).await?;
    let series: Vec<beefy::Series> = if beefy::wants_series(&sessions) || rs.has_tv() {
        fetch(gate, beefy::PATH_SONARR_SERIES, LARGE).await.unwrap_or_default()
    } else {
        Vec::new()
    };
    let anime = beefy::AnimeIndex::from_series(&series);
    let streams = beefy::streams(&sessions, &anime);
    drop(sessions);
    let downloads = beefy::downloads(&radarr, &sonarr, &rs, &series, &night);
    Ok(Snapshot { v: state::SNAPSHOT_VERSION, at, streams, downloads })
}

async fn waker_loop(app: Arc<App>, waker: Option<BaseUrl>, every: Duration) {
    let mut tick = tokio::time::interval(every);
    loop {
        tick.tick().await;
        let w = match &waker {
            Some(u) => waker::status(u).await,
            None => WakerState::Unknown,
        };
        if let Ok(mut s) = app.waker.lock() {
            *s = w;
        }
    }
}

async fn beefy_loop(app: Arc<App>, waker: Option<BaseUrl>, gate: Option<BaseUrl>, every: Duration) {
    let (Some(waker), Some(gate)) = (waker, gate) else { return };
    let mut tick = tokio::time::interval(every);
    tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    loop {
        tick.tick().await;
        let w = waker::status(&waker).await;
        if let Ok(mut s) = app.waker.lock() {
            *s = w;
        }
        if w != WakerState::Up {
            continue;
        }
        match poll_beefy(&gate).await {
            Ok(s) => {
                app.note("");
                app.store(s);
            }
            Err(e) => app.note(&format!("beefy poll failed: {e}")),
        }
    }
}

async fn local_loop(app: Arc<App>, src: local::Sources, every: Duration) {
    let mut tick = tokio::time::interval(every);
    tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    let mut last = Vec::new();
    loop {
        tick.tick().await;
        let (l, errors) = src.refresh(now_ms()).await;
        if errors != last {
            for e in &errors {
                log(&format!("local source unavailable: {e}"));
            }
            last = errors;
        }
        if let Ok(mut s) = app.local.lock() {
            *s = l;
        }
    }
}

fn respond(r: api::Resp, head: bool) -> Response<Full<Bytes>> {
    let csp = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
    let body = if head { Bytes::new() } else { Bytes::from(r.body) };
    let mut b = Response::builder()
        .status(r.status)
        .header("content-type", r.content_type)
        .header("cache-control", "no-store")
        .header("x-content-type-options", "nosniff")
        .header("referrer-policy", "no-referrer");
    if r.content_type.starts_with("text/html") {
        b = b.header("content-security-policy", csp);
    }
    b.body(Full::new(body)).unwrap_or_else(|_| Response::new(Full::new(Bytes::new())))
}

async fn serve(listener: TcpListener, app: Arc<App>) {
    let limit = Arc::new(Semaphore::new(MAX_CONNECTIONS));
    loop {
        let Ok((stream, peer)) = listener.accept().await else {
            tokio::time::sleep(Duration::from_millis(50)).await;
            continue;
        };
        let Ok(permit) = limit.clone().acquire_owned().await else { return };
        let app = app.clone();
        tokio::spawn(async move {
            let _permit = permit;
            let svc = service_fn(move |req: Request<Incoming>| {
                let app = app.clone();
                async move {
                    let method = req.method().as_str().to_string();
                    let path = req.uri().path().to_string();
                    let r = api::route(&method, &path, peer.ip(), &app.access, || app.view());
                    Ok::<_, Infallible>(respond(r, method == "HEAD"))
                }
            });
            let _ = http1::Builder::new()
                .timer(TokioTimer::new())
                .header_read_timeout(Duration::from_secs(10))
                .serve_connection(TokioIo::new(stream), svc)
                .await;
        });
    }
}

/// `--health`: GET /health on the local listen port; exit code for the Docker healthcheck.
fn health(port: u16) -> i32 {
    use std::io::{Read, Write};
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let t = Duration::from_secs(3);
    let Ok(mut s) = std::net::TcpStream::connect_timeout(&addr, t) else { return 1 };
    let _ = s.set_read_timeout(Some(t));
    if s.write_all(b"GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n").is_err() {
        return 1;
    }
    let mut buf = [0u8; 12];
    let n = s.read(&mut buf).unwrap_or(0);
    if buf[..n].starts_with(b"HTTP/1.1 200") || buf[..n].starts_with(b"HTTP/1.0 200") { 0 } else { 1 }
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

fn main() {
    let port: u16 = env_or("LISTEN_PORT", "8080").parse().unwrap_or_else(|_| fail("LISTEN_PORT must be a port"));
    if std::env::args().nth(1).as_deref() == Some("--health") {
        std::process::exit(health(port));
    }
    let bind = env_or("LISTEN_ADDR", "0.0.0.0");
    let waker = url("WAKER_URL", "http://192.168.1.2:9001");
    let gate = url("GATE_URL", "http://192.168.1.102:8097");
    let abs = url("ABS_URL", "http://audiobookshelf:8080").map(|u| (u, PathBuf::from(env_or("ABS_KEY_FILE", "/run/secrets/abs_api_key"))));
    let qbit = url("QBIT_URL", "http://10.24.25.2:8080")
        .map(|u| (u, PathBuf::from(env_or("QBIT_PASS_FILE", "/run/secrets/qbit_pass")), env_or("QBIT_USER", "admin")));
    let poll = env_secs("POLL_SECONDS", 30);
    let waker_every = env_secs("WAKER_SECONDS", 15);
    let access = api::Access {
        page: api::Allow::parse(&env_or("PAGE_ALLOW", "172.24.255.3/32,127.0.0.1/32")).unwrap_or_else(|e| fail(&format!("PAGE_ALLOW: {e}"))),
        metrics: api::Allow::parse(&env_or("METRICS_ALLOW", "10.24.40.0/29,127.0.0.1/32")).unwrap_or_else(|e| fail(&format!("METRICS_ALLOW: {e}"))),
    };
    let data = Some(env_or("DATA_DIR", "/data")).filter(|d| d != "off").map(|d| PathBuf::from(d).join("last.json"));
    let last = data.as_deref().and_then(state::load);
    if let Some(s) = &last {
        log(&format!("loaded the last snapshot from {} s ago", (now() - s.at).max(0)));
    }
    let app = Arc::new(App {
        saved: Mutex::new((last.as_ref().map(|s| s.at).unwrap_or(0), last.as_ref().map(|s| s.downloads.clone()))),
        snap: Mutex::new(last),
        waker: Mutex::new(WakerState::Unknown),
        local: Mutex::new(Local::default()),
        access,
        data,
        last_error: Mutex::new(String::new()),
    });
    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap_or_else(|e| fail(&format!("runtime: {e}")));
    rt.block_on(async move {
        let listener = TcpListener::bind((bind.as_str(), port)).await.unwrap_or_else(|e| fail(&format!("bind {bind}:{port}: {e}")));
        match (&gate, &waker) {
            (Some(g), Some(w)) => log(&format!("listening on {bind}:{port}; beefy via {}:{} only while {}:{} says up, every {} s", g.host, g.port, w.host, w.port, poll.as_secs())),
            _ => log(&format!("listening on {bind}:{port}; beefy polling off (WAKER_URL or GATE_URL = off)")),
        }
        tokio::spawn(waker_loop(app.clone(), waker.clone(), waker_every));
        tokio::spawn(beefy_loop(app.clone(), waker, gate, poll));
        tokio::spawn(local_loop(app.clone(), local::Sources::new(abs, qbit), poll));
        tokio::select! {
            _ = serve(listener, app) => {}
            _ = shutdown() => {}
        }
    });
}
