//! Status page and its JSON API, behind HTTP Basic auth when WEB_USER and WEB_PASS are set.
use std::convert::Infallible;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use http_body_util::Full;
use hyper::body::{Bytes, Incoming};
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper::{Method, Request, Response, StatusCode, header};
use hyper_util::rt::{TokioIo, TokioTimer};
use tokio::net::TcpListener;
use tokio::sync::Semaphore;

use crate::clients;
use crate::events;

const HTML: &str = include_str!("index.html");
const REAL_IP_URL: &str = "https://api.ipify.org";
const REAL_IP_TTL: Duration = Duration::from_secs(600);
const MAX_CONNECTIONS: usize = 64;

pub struct State {
    pub expected_auth: Option<Vec<u8>>,
    pub data_file: PathBuf,
    real_ip: Mutex<Option<(String, Instant)>>,
}

impl State {
    pub fn new(user: &str, pass: &str, data_file: PathBuf) -> Self {
        let expected_auth = (!user.is_empty() && !pass.is_empty()).then(|| clients::basic(user, pass).into_bytes());
        State { expected_auth, data_file, real_ip: Mutex::new(None) }
    }

    /// Public IP of this container's own route (not the VPN), cached 10 min; only successes are cached.
    pub fn real_ip(&self) -> String {
        let cached = self.real_ip.lock().map(|g| g.clone()).unwrap_or(None);
        if let Some((ip, at)) = &cached
            && at.elapsed() <= REAL_IP_TTL
        {
            return ip.clone();
        }
        let fresh = clients::body(clients::agent(Duration::from_secs(5)).get(REAL_IP_URL).call())
            .map(|b| b.trim().to_string())
            .filter(|ip| !ip.is_empty() && ip.len() <= 64 && ip.chars().all(|c| c.is_ascii_hexdigit() || c == '.' || c == ':'));
        match fresh {
            Some(ip) => {
                if let Ok(mut g) = self.real_ip.lock() {
                    *g = Some((ip.clone(), Instant::now()));
                }
                ip
            }
            None => cached.map(|(ip, _)| ip).unwrap_or_else(|| "unknown".into()),
        }
    }
}

/// Constant-time comparison of the Authorization header with the expected one.
pub fn auth_ok(expected: &[u8], got: Option<&[u8]>) -> bool {
    let got = got.unwrap_or(&[]);
    let mut diff = (expected.len() ^ got.len()) as u8 | u8::from(expected.len() != got.len());
    for (i, e) in expected.iter().enumerate() {
        diff |= e ^ got.get(i).copied().unwrap_or(0);
    }
    diff == 0
}

fn reply(code: StatusCode, ctype: Option<&str>, body: impl Into<Bytes>) -> Response<Full<Bytes>> {
    let mut b = Response::builder().status(code);
    if let Some(t) = ctype {
        b = b.header(header::CONTENT_TYPE, t);
    }
    b.body(Full::new(body.into())).unwrap_or_else(|_| Response::new(Full::new(Bytes::new())))
}

async fn read_history(state: &Arc<State>) -> String {
    tokio::fs::read_to_string(&state.data_file).await.unwrap_or_default()
}

pub async fn handle(req: Request<Incoming>, state: Arc<State>) -> Result<Response<Full<Bytes>>, Infallible> {
    if req.method() != Method::GET {
        return Ok(reply(StatusCode::NOT_IMPLEMENTED, None, Bytes::new()));
    }
    if let Some(exp) = &state.expected_auth
        && !auth_ok(exp, req.headers().get(header::AUTHORIZATION).map(|v| v.as_bytes()))
    {
        let mut r = reply(StatusCode::UNAUTHORIZED, None, Bytes::new());
        r.headers_mut().insert(header::WWW_AUTHENTICATE, header::HeaderValue::from_static("Basic realm=\"port-updater\""));
        return Ok(r);
    }
    let target = req.uri().path_and_query().map(|p| p.as_str()).unwrap_or("");
    Ok(match target {
        "/api/history" => reply(StatusCode::OK, Some("application/json"), events::history_json(&read_history(&state).await)),
        "/api/status" => {
            let vpn_ip = events::latest_vpn_ip(&read_history(&state).await);
            let st = state.clone();
            let real_ip = tokio::task::spawn_blocking(move || st.real_ip()).await.unwrap_or_else(|_| "unknown".into());
            let body = serde_json::json!({"real_ip": real_ip, "vpn_ip": vpn_ip}).to_string();
            reply(StatusCode::OK, Some("application/json"), body)
        }
        "/" | "/index.html" => reply(StatusCode::OK, Some("text/html; charset=utf-8"), HTML),
        _ => reply(StatusCode::NOT_FOUND, None, Bytes::new()),
    })
}

pub async fn serve(port: u16, state: Arc<State>) -> std::io::Result<()> {
    let listener = TcpListener::bind(SocketAddr::from(([0, 0, 0, 0], port))).await?;
    println!("[web-server] Listening on port {port}");
    let slots = Arc::new(Semaphore::new(MAX_CONNECTIONS));
    loop {
        let (stream, _) = match listener.accept().await {
            Ok(s) => s,
            Err(_) => continue,
        };
        let Ok(permit) = slots.clone().acquire_owned().await else { continue };
        let state = state.clone();
        tokio::spawn(async move {
            let svc = service_fn(move |req| handle(req, state.clone()));
            let conn = http1::Builder::new()
                .timer(TokioTimer::new())
                .header_read_timeout(Duration::from_secs(10))
                .max_buf_size(64 * 1024)
                .serve_connection(TokioIo::new(stream), svc);
            let _ = tokio::time::timeout(Duration::from_secs(120), conn).await;
            drop(permit);
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn auth_compare() {
        let exp = clients::basic("u", "p").into_bytes();
        assert!(auth_ok(&exp, Some(b"Basic dTpw")));
        assert!(!auth_ok(&exp, Some(b"Basic dTpx")));
        assert!(!auth_ok(&exp, Some(b"Basic dTpw ")));
        assert!(!auth_ok(&exp, Some(b"Basic dTp")));
        assert!(!auth_ok(&exp, Some(b"")));
        assert!(!auth_ok(&exp, None));
    }

    #[test]
    fn auth_only_with_user_and_password() {
        assert!(State::new("u", "", PathBuf::new()).expected_auth.is_none());
        assert!(State::new("", "p", PathBuf::new()).expected_auth.is_none());
        assert!(State::new("u", "p", PathBuf::new()).expected_auth.is_some());
    }
}
