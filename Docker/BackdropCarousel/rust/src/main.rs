#![forbid(unsafe_code)]

use std::io::{self, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, UNIX_EPOCH};

use bytes::Bytes;
use futures_util::TryStreamExt;
use http_body_util::{combinators::BoxBody, BodyExt, Full, StreamBody};
use hyper::body::Frame;
use hyper::header::{self, HeaderValue};
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper::{Method, Request, Response, StatusCode};
use hyper_util::rt::TokioIo;
use tokio::io::{AsyncReadExt, AsyncSeekExt};
use tokio::net::TcpListener;
use tokio_util::io::ReaderStream;

type Body = BoxBody<Bytes, io::Error>;

const MEDIA_TYPES: &[(&str, &str)] = &[
    ("jpg", "image/jpeg"),
    ("jpeg", "image/jpeg"),
    ("png", "image/png"),
    ("webp", "image/webp"),
    ("bmp", "image/bmp"),
    ("gif", "image/gif"),
];

fn media_type(path: &Path) -> Option<&'static str> {
    let ext = path.extension()?.to_str()?.to_ascii_lowercase();
    MEDIA_TYPES.iter().find(|(e, _)| *e == ext).map(|(_, t)| *t)
}

#[derive(Debug, PartialEq)]
enum Route {
    List,
    Random,
    Photo(String),
    NotFound,
}

fn route(raw_path: &str) -> Route {
    let decoded = match percent_encoding::percent_decode_str(raw_path).decode_utf8() {
        Ok(p) => p.into_owned(),
        Err(_) => return Route::NotFound,
    };
    match decoded.as_str() {
        "/" => Route::List,
        "/random" => Route::Random,
        p => match p.strip_prefix("/photo/") {
            Some(name) if !name.is_empty() && !name.contains('/') => Route::Photo(name.to_string()),
            _ => Route::NotFound,
        },
    }
}

#[derive(Debug, PartialEq)]
enum Range {
    Full,
    Part(u64, u64),
    Unsatisfiable,
}

fn parse_range(header: Option<&str>, size: u64) -> Range {
    let Some(spec) = header.and_then(|h| h.trim().strip_prefix("bytes=")) else {
        return Range::Full;
    };
    if spec.contains(',') {
        return Range::Full;
    }
    let Some((a, b)) = spec.trim().split_once('-') else {
        return Range::Full;
    };
    let (a, b) = (a.trim(), b.trim());
    let parsed = match (a.is_empty(), b.is_empty()) {
        (true, true) => return Range::Full,
        (true, false) => match b.parse::<u64>() {
            Ok(0) => return Range::Unsatisfiable,
            Ok(n) => (size.saturating_sub(n), size.saturating_sub(1)),
            Err(_) => return Range::Full,
        },
        (false, _) => match (a.parse::<u64>(), if b.is_empty() { Ok(u64::MAX) } else { b.parse::<u64>() }) {
            (Ok(s), Ok(e)) => (s, e.min(size.saturating_sub(1))),
            _ => return Range::Full,
        },
    };
    if size == 0 || parsed.0 >= size || parsed.0 > parsed.1 {
        return Range::Unsatisfiable;
    }
    Range::Part(parsed.0, parsed.1)
}

fn full(status: StatusCode, ctype: &'static str, body: impl Into<Bytes>) -> Response<Body> {
    let body: Bytes = body.into();
    let mut r = Response::new(Full::new(body).map_err(|never| match never {}).boxed());
    *r.status_mut() = status;
    r.headers_mut().insert(header::CONTENT_TYPE, HeaderValue::from_static(ctype));
    r
}

fn json(status: StatusCode, value: serde_json::Value) -> Response<Body> {
    full(status, "application/json", value.to_string())
}

fn not_found_route() -> Response<Body> {
    json(StatusCode::NOT_FOUND, serde_json::json!({"detail": "Not Found"}))
}

fn not_found_photo() -> Response<Body> {
    json(StatusCode::NOT_FOUND, serde_json::json!({"error": "not found"}))
}

struct App {
    dir: PathBuf,
}

impl App {
    fn photos(&self) -> Vec<PathBuf> {
        let Ok(entries) = std::fs::read_dir(&self.dir) else {
            return Vec::new();
        };
        let mut out: Vec<PathBuf> = entries
            .filter_map(|e| e.ok())
            .map(|e| e.path())
            .filter(|p| media_type(p).is_some() && std::fs::metadata(p).map(|m| m.is_file()).unwrap_or(false))
            .collect();
        out.sort();
        out
    }

    fn resolve(&self, name: &str) -> Option<(PathBuf, &'static str)> {
        if name.contains('\0') {
            return None;
        }
        let root = self.dir.canonicalize().ok()?;
        let path = self.dir.join(name).canonicalize().ok()?;
        if !path.starts_with(&root) || !path.is_file() {
            return None;
        }
        let ctype = media_type(&path)?;
        Some((path, ctype))
    }
}

async fn serve_file(path: &Path, ctype: &'static str, range: Option<&str>, if_none_match: Option<&str>) -> Response<Body> {
    let Ok(mut file) = tokio::fs::File::open(path).await else {
        return not_found_photo();
    };
    let Ok(meta) = file.metadata().await else {
        return not_found_photo();
    };
    let size = meta.len();
    let mtime = meta.modified().ok();
    let nanos = mtime.and_then(|t| t.duration_since(UNIX_EPOCH).ok()).map(|d| d.as_nanos()).unwrap_or(0);
    let etag = format!("\"{size:x}-{nanos:x}\"");
    let mut builder = Response::builder()
        .header(header::CONTENT_TYPE, ctype)
        .header(header::ACCEPT_RANGES, "bytes")
        .header(header::ETAG, &etag);
    if let Some(t) = mtime {
        builder = builder.header(header::LAST_MODIFIED, httpdate::fmt_http_date(t));
    }
    if if_none_match.is_some_and(|v| v.split(',').any(|t| t.trim() == etag || t.trim() == "*")) {
        return builder.status(StatusCode::NOT_MODIFIED).body(empty()).unwrap_or_else(|_| not_found_photo());
    }
    let (status, start, len) = match parse_range(range, size) {
        Range::Full => (StatusCode::OK, 0, size),
        Range::Part(s, e) => {
            builder = builder.header(header::CONTENT_RANGE, format!("bytes {s}-{e}/{size}"));
            (StatusCode::PARTIAL_CONTENT, s, e - s + 1)
        }
        Range::Unsatisfiable => {
            return builder
                .status(StatusCode::RANGE_NOT_SATISFIABLE)
                .header(header::CONTENT_RANGE, format!("bytes */{size}"))
                .body(empty())
                .unwrap_or_else(|_| not_found_photo());
        }
    };
    if start > 0 && file.seek(io::SeekFrom::Start(start)).await.is_err() {
        return not_found_photo();
    }
    let stream = ReaderStream::with_capacity(file.take(len), 64 * 1024).map_ok(Frame::data);
    builder
        .status(status)
        .header(header::CONTENT_LENGTH, len)
        .body(BodyExt::boxed(StreamBody::new(stream)))
        .unwrap_or_else(|_| not_found_photo())
}

fn empty() -> Body {
    Full::new(Bytes::new()).map_err(|never| match never {}).boxed()
}

fn header_str<'a>(req: &'a Request<hyper::body::Incoming>, name: header::HeaderName) -> Option<&'a str> {
    req.headers().get(name).and_then(|v| v.to_str().ok())
}

async fn handle(app: Arc<App>, req: Request<hyper::body::Incoming>) -> Result<Response<Body>, io::Error> {
    let r = route(req.uri().path());
    if r == Route::NotFound {
        return Ok(not_found_route());
    }
    if req.method() != Method::GET && req.method() != Method::HEAD {
        let mut resp = json(StatusCode::METHOD_NOT_ALLOWED, serde_json::json!({"detail": "Method Not Allowed"}));
        resp.headers_mut().insert(header::ALLOW, HeaderValue::from_static("GET"));
        return Ok(resp);
    }
    let range = header_str(&req, header::RANGE);
    let inm = header_str(&req, header::IF_NONE_MATCH);
    Ok(match r {
        Route::List => {
            let host = header_str(&req, header::HOST).unwrap_or("localhost");
            let photos = tokio::task::spawn_blocking({
                let app = app.clone();
                move || app.photos()
            })
            .await
            .unwrap_or_default();
            let list: Vec<serde_json::Value> = photos
                .iter()
                .filter_map(|p| p.file_name()?.to_str())
                .map(|n| serde_json::json!({"name": n, "url": format!("http://{host}/photo/{n}")}))
                .collect();
            json(StatusCode::OK, serde_json::Value::Array(list))
        }
        Route::Random => {
            let photos = tokio::task::spawn_blocking({
                let app = app.clone();
                move || app.photos()
            })
            .await
            .unwrap_or_default();
            match fastrand::choice(photos.iter()) {
                Some(p) => match media_type(p) {
                    Some(ctype) => serve_file(p, ctype, range, inm).await,
                    None => not_found_photo(),
                },
                None => json(StatusCode::NOT_FOUND, serde_json::json!({"error": "no photos available"})),
            }
        }
        Route::Photo(name) => match app.resolve(&name) {
            Some((path, ctype)) => serve_file(&path, ctype, range, inm).await,
            None => not_found_photo(),
        },
        Route::NotFound => not_found_route(),
    })
}

fn healthcheck(addr: &str) -> io::Result<()> {
    let addr: SocketAddr = addr.replace("0.0.0.0", "127.0.0.1").parse().map_err(|_| io::Error::other("bad LISTEN"))?;
    let mut s = TcpStream::connect_timeout(&addr, Duration::from_secs(3))?;
    s.set_read_timeout(Some(Duration::from_secs(3)))?;
    s.write_all(b"GET / HTTP/1.0\r\nHost: healthcheck\r\n\r\n")?;
    let mut head = [0u8; 12];
    s.read_exact(&mut head)?;
    if &head[9..12] == b"200" {
        Ok(())
    } else {
        Err(io::Error::other("not 200"))
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let listen = std::env::var("LISTEN").unwrap_or_else(|_| "0.0.0.0:8000".into());
    if std::env::args().nth(1).as_deref() == Some("healthcheck") {
        std::process::exit(if healthcheck(&listen).is_ok() { 0 } else { 1 });
    }
    let app = Arc::new(App { dir: PathBuf::from(std::env::var("PHOTOS_DIR").unwrap_or_else(|_| "/photos".into())) });
    let addr: SocketAddr = listen.parse().expect("LISTEN must be host:port");
    let listener = TcpListener::bind(addr).await.expect("bind");
    println!("backdrop-carousel {} listening on {addr}, photos in {}", env!("CARGO_PKG_VERSION"), app.dir.display());
    let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()).expect("signal");
    loop {
        tokio::select! {
            accepted = listener.accept() => {
                let Ok((stream, _)) = accepted else { continue };
                let app = app.clone();
                tokio::spawn(async move {
                    let conn = http1::Builder::new()
                        .timer(hyper_util::rt::TokioTimer::new())
                        .header_read_timeout(Duration::from_secs(10))
                        .serve_connection(TokioIo::new(stream), service_fn(move |req| handle(app.clone(), req)));
                    let _ = tokio::time::timeout(Duration::from_secs(300), conn).await;
                });
            }
            _ = term.recv() => break,
            _ = tokio::signal::ctrl_c() => break,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn routes() {
        assert_eq!(route("/"), Route::List);
        assert_eq!(route("/random"), Route::Random);
        assert_eq!(route("/photo/a.jpg"), Route::Photo("a.jpg".into()));
        assert_eq!(route("/photo/a%2Ejpg"), Route::Photo("a.jpg".into()));
        assert_eq!(route("/photo/g%20h.jpg"), Route::Photo("g h.jpg".into()));
        assert_eq!(route("/photo/..%2Fx.jpg"), Route::NotFound);
        assert_eq!(route("/photo/"), Route::NotFound);
        assert_eq!(route("/photo"), Route::NotFound);
        assert_eq!(route("/random/x"), Route::NotFound);
        assert_eq!(route("/photo/%ff.jpg"), Route::NotFound);
    }

    #[test]
    fn media_types_case_insensitive() {
        assert_eq!(media_type(Path::new("x.JPG")), Some("image/jpeg"));
        assert_eq!(media_type(Path::new("x.webp")), Some("image/webp"));
        assert_eq!(media_type(Path::new("x.txt")), None);
        assert_eq!(media_type(Path::new("jpg")), None);
    }

    #[test]
    fn ranges() {
        assert_eq!(parse_range(None, 100), Range::Full);
        assert_eq!(parse_range(Some("bytes=0-9"), 100), Range::Part(0, 9));
        assert_eq!(parse_range(Some("bytes=90-"), 100), Range::Part(90, 99));
        assert_eq!(parse_range(Some("bytes=-5"), 100), Range::Part(95, 99));
        assert_eq!(parse_range(Some("bytes=-500"), 100), Range::Part(0, 99));
        assert_eq!(parse_range(Some("bytes=50-500"), 100), Range::Part(50, 99));
        assert_eq!(parse_range(Some("bytes=100-"), 100), Range::Unsatisfiable);
        assert_eq!(parse_range(Some("bytes=9-3"), 100), Range::Unsatisfiable);
        assert_eq!(parse_range(Some("bytes=0-1,5-6"), 100), Range::Full);
        assert_eq!(parse_range(Some("items=0-1"), 100), Range::Full);
        assert_eq!(parse_range(Some("bytes=x-1"), 100), Range::Full);
    }

    #[test]
    fn resolve_stays_inside_dir() {
        let base = std::env::temp_dir().join(format!("bd-test-{}", std::process::id()));
        let dir = base.join("photos");
        std::fs::create_dir_all(dir.join("sub")).unwrap();
        std::fs::write(dir.join("a.jpg"), b"a").unwrap();
        std::fs::write(dir.join("n.txt"), b"n").unwrap();
        std::fs::write(base.join("secret.jpg"), b"s").unwrap();
        let app = App { dir: dir.clone() };
        assert!(app.resolve("a.jpg").is_some());
        assert!(app.resolve("n.txt").is_none());
        assert!(app.resolve("sub").is_none());
        assert!(app.resolve("..").is_none());
        assert!(app.resolve("../secret.jpg").is_none());
        assert!(app.resolve("a.jpg\0").is_none());
        assert_eq!(app.photos(), vec![dir.join("a.jpg")]);
        std::fs::remove_dir_all(&base).unwrap();
    }
}
