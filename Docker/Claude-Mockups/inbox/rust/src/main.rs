#![forbid(unsafe_code)]

use std::io::Write;
use std::net::SocketAddr;
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use bytes::Bytes;
use http_body_util::{BodyExt, Full, Limited};
use hyper::body::Incoming;
use hyper::header::{HeaderValue, CONTENT_TYPE};
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper::{Method, Request, Response, StatusCode};
use hyper_util::rt::{TokioIo, TokioTimer};
use serde_json::{json, Map, Value};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::Semaphore;

const MAX_BODY: usize = 64 * 1024;
const NOTE_MAX_UNITS: usize = 2000;
const MAX_CONNECTIONS: usize = 128;
const HEADER_TIMEOUT: Duration = Duration::from_secs(30);
const BODY_TIMEOUT: Duration = Duration::from_secs(60);

static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

fn valid_token(t: &str) -> bool {
    (6..=64).contains(&t.len()) && t.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

fn truncate_utf16(s: &str, max_units: usize) -> String {
    let mut units = 0;
    let mut out = String::new();
    for c in s.chars() {
        units += c.len_utf16();
        if units > max_units {
            break;
        }
        out.push(c);
    }
    out
}

fn iso_timestamp(t: SystemTime) -> String {
    let d = t.duration_since(UNIX_EPOCH).unwrap_or_default();
    let (secs, ms) = (d.as_secs() as i64, d.subsec_millis());
    let (days, rem) = (secs.div_euclid(86400), secs.rem_euclid(86400));
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}.{ms:03}Z",
        rem / 3600,
        rem % 3600 / 60,
        rem % 60
    )
}

enum Parsed {
    BadJson,
    BadToken,
    Ok(String, Value),
}

fn build_record(body: &[u8], now: SystemTime) -> Parsed {
    let Ok(payload) = serde_json::from_slice::<Value>(body) else {
        return Parsed::BadJson;
    };
    let Some(token) = payload.get("token").and_then(Value::as_str).filter(|t| valid_token(t)) else {
        return Parsed::BadToken;
    };
    let mut rec = Map::new();
    rec.insert("token".into(), json!(token));
    rec.insert("choice".into(), payload.get("choice").filter(|v| !v.is_null()).cloned().unwrap_or(Value::Null));
    if let Some(v) = payload.get("choices").filter(|v| v.is_array()) {
        rec.insert("choices".into(), v.clone());
    }
    if let Some(s) = payload.get("label").and_then(Value::as_str) {
        rec.insert("label".into(), json!(s));
    }
    if let Some(s) = payload.get("note").and_then(Value::as_str) {
        rec.insert("note".into(), json!(truncate_utf16(s, NOTE_MAX_UNITS)));
    }
    rec.insert("receivedAt".into(), json!(iso_timestamp(now)));
    Parsed::Ok(token.to_string(), Value::Object(rec))
}

fn write_atomic(dir: &PathBuf, token: &str, text: &str) -> std::io::Result<()> {
    let file = dir.join(format!("{token}.json"));
    let tmp = dir.join(format!("{token}.json.{}.{}.tmp", std::process::id(), TMP_SEQ.fetch_add(1, Ordering::Relaxed)));
    let res = (|| {
        let mut f = std::fs::OpenOptions::new().write(true).create_new(true).mode(0o666).open(&tmp)?;
        f.write_all(text.as_bytes())?;
        drop(f);
        std::fs::rename(&tmp, &file)
    })();
    if res.is_err() {
        let _ = std::fs::remove_file(&tmp);
    }
    res
}

fn reply(code: StatusCode, body: &'static str) -> Response<Full<Bytes>> {
    let mut r = Response::new(Full::new(Bytes::from_static(body.as_bytes())));
    *r.status_mut() = code;
    r.headers_mut().insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
    r
}

fn no_content() -> Response<Full<Bytes>> {
    let mut r = Response::new(Full::new(Bytes::new()));
    *r.status_mut() = StatusCode::NO_CONTENT;
    r
}

type HandlerResult = Result<Response<Full<Bytes>>, Box<dyn std::error::Error + Send + Sync>>;

async fn handle(req: Request<Incoming>, dir: Arc<PathBuf>) -> HandlerResult {
    let target = req.uri().path_and_query().map(|p| p.as_str()).unwrap_or("");
    match (req.method(), target) {
        (&Method::GET, "/health") => Ok(reply(StatusCode::OK, r#"{"ok":true}"#)),
        (&Method::POST, "/submit") => {
            // an oversize or stalled body drops the connection without a response
            let collected = tokio::time::timeout(BODY_TIMEOUT, Limited::new(req.into_body(), MAX_BODY).collect()).await??;
            let body = collected.to_bytes();
            match build_record(&body, SystemTime::now()) {
                Parsed::BadJson => Ok(reply(StatusCode::BAD_REQUEST, r#"{"error":"invalid json"}"#)),
                Parsed::BadToken => Ok(reply(StatusCode::BAD_REQUEST, r#"{"error":"invalid token"}"#)),
                Parsed::Ok(token, rec) => {
                    let text = serde_json::to_string_pretty(&rec)?;
                    // one small file: cheaper inline than a thread hop
                    let written = write_atomic(&dir, &token, &text);
                    Ok(match written {
                        Ok(()) => no_content(),
                        Err(_) => reply(StatusCode::INTERNAL_SERVER_ERROR, r#"{"error":"write failed"}"#),
                    })
                }
            }
        }
        _ => Ok(reply(StatusCode::NOT_FOUND, r#"{"error":"not found"}"#)),
    }
}

async fn serve(stream: TcpStream, dir: Arc<PathBuf>) {
    let svc = service_fn(move |req| handle(req, dir.clone()));
    let _ = http1::Builder::new()
        .timer(TokioTimer::new())
        .header_read_timeout(HEADER_TIMEOUT)
        .max_buf_size(16 * 1024)
        .serve_connection(TokioIo::new(stream), svc)
        .await;
}

fn port() -> Result<u16, String> {
    let p = std::env::var("PORT").unwrap_or_else(|_| "8080".into());
    p.parse().map_err(|_| format!("invalid PORT: {p}"))
}

async fn health_probe(port: u16) -> bool {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let run = async {
        let mut s = TcpStream::connect(("127.0.0.1", port)).await.ok()?;
        s.write_all(b"GET /health HTTP/1.0\r\n\r\n").await.ok()?;
        let mut buf = Vec::new();
        s.read_to_end(&mut buf).await.ok()?;
        Some(buf.starts_with(b"HTTP/1.") && buf.get(8..).is_some_and(|r| r.starts_with(b" 200")))
    };
    matches!(tokio::time::timeout(Duration::from_secs(3), run).await, Ok(Some(true)))
}

async fn bind(port: u16) -> std::io::Result<TcpListener> {
    match TcpListener::bind(SocketAddr::from(([0u16; 8], port))).await {
        Ok(l) => Ok(l),
        Err(_) => TcpListener::bind(SocketAddr::from(([0, 0, 0, 0], port))).await,
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let port = match port() {
        Ok(p) => p,
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(1);
        }
    };
    if std::env::args().nth(1).as_deref() == Some("--health") {
        std::process::exit(if health_probe(port).await { 0 } else { 1 });
    }
    let data_dir = std::env::var("DATA_DIR").unwrap_or_else(|_| "/data".into());
    let listener = match bind(port).await {
        Ok(l) => l,
        Err(e) => {
            eprintln!("cannot listen on :{port}: {e}");
            std::process::exit(1);
        }
    };
    println!("answer-inbox listening on :{port}, writing to {data_dir}");
    let dir = Arc::new(PathBuf::from(data_dir));
    let permits = Arc::new(Semaphore::new(MAX_CONNECTIONS));
    let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()).expect("sigterm handler");
    let mut int = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::interrupt()).expect("sigint handler");
    loop {
        let permit = tokio::select! {
            _ = term.recv() => break,
            _ = int.recv() => break,
            p = permits.clone().acquire_owned() => p.expect("semaphore open"),
        };
        tokio::select! {
            _ = term.recv() => break,
            _ = int.recv() => break,
            accepted = listener.accept() => {
                let Ok((stream, _)) = accepted else { continue };
                let dir = dir.clone();
                tokio::spawn(async move {
                    serve(stream, dir).await;
                    drop(permit);
                });
            }
        }
    }
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tokens() {
        assert!(valid_token("abcdef") && valid_token("a-b_C9") && valid_token(&"a".repeat(64)));
        for bad in ["abcde", "", "abcdef\n", "ab.cdef", "../abcdef", "abcdeé", &"a".repeat(65)] {
            assert!(!valid_token(bad), "{bad:?}");
        }
    }

    #[test]
    fn timestamps() {
        assert_eq!(iso_timestamp(UNIX_EPOCH), "1970-01-01T00:00:00.000Z");
        assert_eq!(iso_timestamp(UNIX_EPOCH + Duration::from_millis(1_709_164_800_123)), "2024-02-29T00:00:00.123Z");
        assert_eq!(iso_timestamp(UNIX_EPOCH + Duration::from_secs(4_102_444_799)), "2099-12-31T23:59:59.000Z");
    }

    #[test]
    fn note_cut_counts_utf16_units() {
        assert_eq!(truncate_utf16("abc", 2), "ab");
        assert_eq!(truncate_utf16(&"😀".repeat(5), 5).chars().count(), 2);
    }

    #[test]
    fn record_layout() {
        let Parsed::Ok(t, v) = build_record(br#"{"note":"n","token":"abcdef","extra":1}"#, UNIX_EPOCH) else { panic!() };
        assert_eq!(t, "abcdef");
        assert_eq!(
            serde_json::to_string_pretty(&v).unwrap(),
            "{\n  \"token\": \"abcdef\",\n  \"choice\": null,\n  \"note\": \"n\",\n  \"receivedAt\": \"1970-01-01T00:00:00.000Z\"\n}"
        );
        assert!(matches!(build_record(b"null", UNIX_EPOCH), Parsed::BadToken));
        assert!(matches!(build_record(b"{", UNIX_EPOCH), Parsed::BadJson));
    }
}
