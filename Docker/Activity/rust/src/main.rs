//! Activity: anonymous "who is watching / listening, what is downloading" for the homelab status page.
//! Polls only while someone views the page; pulls beefy only while Beefy-Waker /status says it is up (never wakes it), through the read-only activity-gate.
#![forbid(unsafe_code)]

mod api;
mod beefy;
mod client;
mod demand;
mod local;
mod state;
mod waker;

use std::collections::HashSet;
use std::convert::Infallible;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
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
use demand::Demand;
use state::{DownloadsPart, Local, Polled, StreamsPart, WakerState};

const GATE_TIMEOUT: Duration = Duration::from_secs(3);
const SMALL: usize = 2 << 20;
const LARGE: usize = 4 << 20;
/// The last snapshot is rewritten when the downloads change, else at most this often.
const SAVE_EVERY: i64 = 600;
const MAX_CONNECTIONS: usize = 64;
/// The first view after an idle spell waits at most this long for its immediate poll.
const FIRST_VIEW_WAIT: Duration = Duration::from_secs(4);

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
    streams: Mutex<Option<StreamsPart>>,
    downloads: Mutex<Option<DownloadsPart>>,
    waker: Mutex<WakerState>,
    local: Mutex<Local>,
    access: api::Access,
    data: Option<PathBuf>,
    saved: Mutex<(i64, Option<Vec<state::Download>>)>,
    last_error: Mutex<String>,
    local_errors: Mutex<Vec<String>>,
    polled: Mutex<Polled>,
    demand: Demand,
    poller_alive: AtomicBool,
}

impl App {
    fn view(&self) -> api::Seen {
        let t = now();
        let streams = self.streams.lock().map(|s| s.clone()).unwrap_or(None);
        let downloads = self.downloads.lock().map(|s| s.clone()).unwrap_or(None);
        let waker = self.waker.lock().map(|w| *w).unwrap_or(WakerState::Unknown);
        let local = self.local.lock().map(|l| *l).unwrap_or_default();
        let polled = self.polled.lock().map(|p| *p).unwrap_or_default();
        let last = streams.as_ref().map(|s| s.at).max(downloads.as_ref().map(|d| d.at));
        let age = last.map(|at| (t - at).max(0));
        (state::view(t, streams.as_ref(), downloads.as_ref(), waker, &local, polled), age, self.demand.active())
    }

    fn poller_ok(&self) -> bool {
        self.poller_alive.load(Ordering::Relaxed) && !self.demand.overdue()
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

    fn store_downloads(&self, d: DownloadsPart) {
        if let Some(path) = &self.data {
            if let Ok(mut saved) = self.saved.lock() {
                // also when the clock went back (a saved time in the future would block the periodic save)
                if saved.1.as_ref() != Some(&d.list) || d.at - saved.0 >= SAVE_EVERY || d.at < saved.0 {
                    match state::save(path, &d) {
                        Ok(()) => *saved = (d.at, Some(d.list.clone())),
                        Err(e) => log(&format!("saving {}: {e}", path.display())),
                    }
                }
            }
        }
        if let Ok(mut slot) = self.downloads.lock() {
            *slot = Some(d);
        }
    }
}

async fn fetch<T: DeserializeOwned>(gate: &BaseUrl, path: &str, limit: usize) -> Result<T, String> {
    let body = client::get(gate, path, &[("accept", "application/json")], limit, GATE_TIMEOUT).await.map_err(|e| format!("{path}: {e}"))?;
    serde_json::from_slice(&body).map_err(|_| format!("{path}: unreadable answer"))
}

/// One poll of beefy: the streams and the downloads succeed or fail on their own; `problems` holds every failed path (for one log line).
struct BeefyPoll {
    streams: Result<StreamsPart, ()>,
    downloads: Result<DownloadsPart, ()>,
    problems: Vec<String>,
}

/// One poll through the gate, one attempt per path, side by side; raw answers are dropped as soon as they are grouped.
async fn poll_beefy(gate: &BaseUrl) -> BeefyPoll {
    let at = now();
    let (sessions, rs, night, radarr, sonarr) = tokio::join!(
        fetch::<Vec<beefy::Session>>(gate, beefy::PATH_SESSIONS, SMALL),
        fetch::<beefy::RequestState>(gate, beefy::PATH_REQUEST_STATE, SMALL),
        fetch::<beefy::NightWaiting>(gate, beefy::PATH_NIGHT_WAITING, SMALL),
        fetch::<beefy::Queue>(gate, beefy::PATH_RADARR_QUEUE, LARGE),
        fetch::<beefy::Queue>(gate, beefy::PATH_SONARR_QUEUE, LARGE),
    );
    let mut problems = Vec::new();
    let wanted = sessions.as_ref().is_ok_and(|s| beefy::wants_series(s)) || rs.as_ref().is_ok_and(|r| r.has_tv());
    let mut series_unavailable = false;
    let series: Vec<beefy::Series> = if wanted {
        fetch(gate, beefy::PATH_SONARR_SERIES, LARGE).await.unwrap_or_else(|e| {
            problems.push(e);
            series_unavailable = true;
            Vec::new()
        })
    } else {
        Vec::new()
    };
    let anime = beefy::AnimeIndex::from_series(&series);
    let streams = match sessions {
        Ok(s) => Ok(StreamsPart { at, streams: beefy::streams(&s, &anime), series_unavailable }),
        Err(e) => {
            problems.insert(0, e);
            Err(())
        }
    };
    let night_unavailable = night.is_err();
    let night = night.map(|n| n.ids()).unwrap_or_else(|e| {
        problems.push(e);
        HashSet::new()
    });
    let downloads = match (rs, radarr, sonarr) {
        (Ok(rs), Ok(radarr), Ok(sonarr)) => {
            let mut truncated = false;
            for (name, q) in [("radarr", &radarr), ("sonarr", &sonarr)] {
                if let Some((n, total)) = q.truncated() {
                    problems.push(format!("{name} queue truncated: {n} of {total} records"));
                    truncated = true;
                }
            }
            let gaps = state::Gaps { series_unavailable, night_unavailable, truncated };
            Ok(DownloadsPart { at, list: beefy::downloads(&radarr, &sonarr, &rs, &series, &night), gaps })
        }
        (rs, radarr, sonarr) => {
            problems.extend([rs.err(), radarr.err(), sonarr.err()].into_iter().flatten());
            Err(())
        }
    };
    BeefyPoll { streams, downloads, problems }
}

/// Waker, then beefy if it says up; returns (streams failed, downloads failed).
async fn poll_beefy_side(app: &App, waker: Option<&BaseUrl>, gate: Option<&BaseUrl>) -> (bool, bool) {
    let w = match waker {
        Some(u) => waker::status(u).await,
        None => WakerState::Unknown,
    };
    let prev = app.waker.lock().map(|mut s| std::mem::replace(&mut *s, w)).unwrap_or(WakerState::Unknown);
    if let Ok(mut p) = app.polled.lock() {
        p.up_since = match (w, prev) {
            (WakerState::Up, WakerState::Down | WakerState::Waking | WakerState::Broken) => Some(now()),
            (WakerState::Up, _) => p.up_since,
            _ => None,
        };
    }
    let Some(gate) = gate.filter(|_| w == WakerState::Up) else { return (false, false) };
    let p = poll_beefy(gate).await;
    let failed = (p.streams.is_err(), p.downloads.is_err());
    if let Ok(s) = p.streams {
        if let Ok(mut slot) = app.streams.lock() {
            *slot = Some(s);
        }
    }
    if let Ok(d) = p.downloads {
        app.store_downloads(d);
    }
    let lead = if failed.0 || failed.1 { "beefy poll failed" } else { "beefy poll incomplete" };
    app.note(&if p.problems.is_empty() { String::new() } else { format!("{lead}: {}", p.problems.join("; ")) });
    failed
}

async fn poll_local(app: &App, src: &local::Sources) {
    let (l, errors) = src.refresh(now_ms()).await;
    if let Ok(mut last) = app.local_errors.lock() {
        if errors != *last {
            for e in &errors {
                log(&format!("local source unavailable: {e}"));
            }
            *last = errors;
        }
    }
    if let Ok(mut s) = app.local.lock() {
        *s = l;
    }
}

/// One poll of every source: Waker (and beefy behind it) alongside the fastpi sources.
async fn poll_once(app: &App, waker: Option<&BaseUrl>, gate: Option<&BaseUrl>, src: &local::Sources) {
    let ((streams_failed, downloads_failed), ()) = tokio::join!(poll_beefy_side(app, waker, gate.filter(|_| waker.is_some())), poll_local(app, src));
    if let Ok(mut p) = app.polled.lock() {
        *p = Polled { at: Some(now()), streams_failed, downloads_failed, up_since: p.up_since };
    }
}

/// POLL_SECONDS 1..=86400 (0 would hammer beefy); VIEWER_SECONDS 1 s to a week.
fn check_timing(poll: Duration, window: Duration) -> Result<(), String> {
    if poll.is_zero() || poll > Duration::from_secs(86_400) {
        return Err("POLL_SECONDS must be 1..86400".into());
    }
    if window.is_zero() || window > Duration::from_secs(7 * 86_400) {
        return Err("VIEWER_SECONDS must be 1 s to a week".into());
    }
    Ok(())
}

/// Clears `poller_alive` when the poll task ends, also by a panic.
struct Alive(Arc<App>);

impl Drop for Alive {
    fn drop(&mut self) {
        self.0.poller_alive.store(false, Ordering::Relaxed);
        log("poll loop stopped");
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
        if !api::admitted(peer.ip(), &app.access) {
            continue;
        }
        let Ok(permit) = limit.clone().try_acquire_owned() else { continue };
        let app = app.clone();
        tokio::spawn(async move {
            let _permit = permit;
            let svc = service_fn(move |req: Request<Incoming>| {
                let app = app.clone();
                async move {
                    let method = req.method().as_str().to_string();
                    let path = req.uri().path().to_string();
                    if api::is_viewer(&method, &path, peer.ip(), &app.access) {
                        if let Some(target) = app.demand.viewer() {
                            app.demand.wait(target, FIRST_VIEW_WAIT).await;
                        }
                    }
                    let r = api::route_health(&method, &path, peer.ip(), &app.access, app.poller_ok(), || app.view());
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
    let waker = url("WAKER_URL", "http://traefik:8080/activity/waker");
    let gate = url("GATE_URL", "http://traefik:8080/activity/gate");
    let abs = url("ABS_URL", "http://audiobookshelf:8080").map(|u| (u, PathBuf::from(env_or("ABS_KEY_FILE", "/run/secrets/abs_api_key"))));
    let qbit = url("QBIT_URL", "http://traefik:8080/activity/qbit");
    let poll = env_secs("POLL_SECONDS", 30);
    let window = env_secs("VIEWER_SECONDS", 120);
    check_timing(poll, window).unwrap_or_else(|e| fail(&e));
    let access = api::Access {
        page: api::Allow::parse(&env_or("PAGE_ALLOW", "172.24.255.3/32,127.0.0.1/32")).unwrap_or_else(|e| fail(&format!("PAGE_ALLOW: {e}"))),
        metrics: api::Allow::parse(&env_or("METRICS_ALLOW", "10.24.40.0/29,127.0.0.1/32")).unwrap_or_else(|e| fail(&format!("METRICS_ALLOW: {e}"))),
    };
    let data = Some(env_or("DATA_DIR", "/data")).filter(|d| d != "off").map(|d| PathBuf::from(d).join("last.json"));
    let last = data.as_deref().and_then(state::load);
    if let Some(d) = &last {
        log(&format!("loaded the last downloads from {} s ago", (now() - d.at).max(0)));
    }
    let app = Arc::new(App {
        saved: Mutex::new((last.as_ref().map(|d| d.at).unwrap_or(0), last.as_ref().map(|d| d.list.clone()))),
        streams: Mutex::new(None),
        downloads: Mutex::new(last),
        waker: Mutex::new(WakerState::Unknown),
        local: Mutex::new(Local::default()),
        access,
        data,
        last_error: Mutex::new(String::new()),
        local_errors: Mutex::new(Vec::new()),
        polled: Mutex::new(Polled::default()),
        demand: Demand::new(poll, window),
        poller_alive: AtomicBool::new(true),
    });
    let src = local::Sources::new(abs, qbit);
    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap_or_else(|e| fail(&format!("runtime: {e}")));
    rt.block_on(async move {
        let listener = TcpListener::bind((bind.as_str(), port)).await.unwrap_or_else(|e| fail(&format!("bind {bind}:{port}: {e}")));
        match (&gate, &waker) {
            (Some(g), Some(w)) => log(&format!("listening on {bind}:{port}; polls every {} s only within {} s of a page view; beefy via {}:{}{} only while {}:{}{} says up", poll.as_secs(), window.as_secs(), g.host, g.port, g.base, w.host, w.port, w.base)),
            _ => log(&format!("listening on {bind}:{port}; polls every {} s only within {} s of a page view; beefy polling off (WAKER_URL or GATE_URL = off)", poll.as_secs(), window.as_secs())),
        }
        let poller = app.clone();
        tokio::spawn(async move {
            let _alive = Alive(poller.clone());
            let app = poller.clone();
            poller.demand.run(|| poll_once(&app, waker.as_ref(), gate.as_ref(), &src)).await
        });
        tokio::select! {
            _ = serve(listener, app) => {}
            _ = shutdown() => {}
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nonsense_poll_config_is_refused() {
        let s = Duration::from_secs;
        assert!(check_timing(s(30), s(120)).is_ok());
        assert!(check_timing(s(1), s(2)).is_ok(), "the black-box suite polls every second");
        assert!(check_timing(s(0), s(120)).is_err(), "0 = a hot loop against beefy");
        assert!(check_timing(s(30), s(0)).is_err());
        assert!(check_timing(s(86_401), s(90_000)).is_err());
    }
}
