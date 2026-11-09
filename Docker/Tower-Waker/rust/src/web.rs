//! Minimal HTTP/1 server layer shared by the wakers (same file in Beefy-Waker and Tower-Waker).
//! Mirrors the Python http.server behaviour the clients rely on: GET/POST only (else 501),
//! urlparse-style path, parse_qs-style query, per-request access log lines.

use std::convert::Infallible;
use std::future::Future;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use http_body_util::Full;
use hyper::body::{Bytes, Incoming};
use hyper::header::{HeaderValue, CONNECTION, CONTENT_TYPE, RETRY_AFTER};
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper::{Request, Response, StatusCode};
use hyper_util::rt::{TokioIo, TokioTimer};
use tokio::net::TcpListener;
use tokio::sync::Semaphore;

const MAX_CONNECTIONS: usize = 512;
const HEADER_TIMEOUT: Duration = Duration::from_secs(10);

pub struct Req {
    pub method: String,
    pub target: String,
    pub peer: String,
    headers: Vec<(String, String)>,
}

impl Req {
    pub fn new(method: &str, target: &str, peer: &str, headers: Vec<(String, String)>) -> Self {
        let headers = headers.into_iter().map(|(k, v)| (k.to_ascii_lowercase(), v)).collect();
        Req { method: method.to_string(), target: target.to_string(), peer: peer.to_string(), headers }
    }

    /// First header with this name (case-insensitive), decoded as latin-1 like http.server.
    pub fn header(&self, name: &str) -> Option<&str> {
        let name = name.to_ascii_lowercase();
        self.headers.iter().find(|(k, _)| *k == name).map(|(_, v)| v.as_str())
    }

    pub fn header_or(&self, name: &str) -> &str {
        self.header(name).unwrap_or("")
    }

    /// `urlparse(path).path.rstrip("/") or "/"`
    pub fn route(&self) -> String {
        let p = url_parts(&self.target).0;
        let p = p.trim_end_matches('/');
        if p.is_empty() { "/".to_string() } else { p.to_string() }
    }

    pub fn query(&self) -> String {
        url_parts(&self.target).1
    }
}

/// (path, query) the way Python's urlparse splits them (scheme, netloc, params and fragment dropped).
pub fn url_parts(target: &str) -> (String, String) {
    let mut u = target;
    if let Some(i) = u.find(':') {
        let scheme = &u[..i];
        if i > 0
            && scheme.as_bytes()[0].is_ascii_alphabetic()
            && scheme.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'+' || b == b'-' || b == b'.')
        {
            u = &u[i + 1..];
        }
    }
    if let Some(rest) = u.strip_prefix("//") {
        let end = rest.find(['/', '?', '#']).unwrap_or(rest.len());
        u = &rest[end..];
    }
    if let Some(i) = u.find('#') {
        u = &u[..i];
    }
    let (mut path, query) = match u.find('?') {
        Some(i) => (&u[..i], &u[i + 1..]),
        None => (u, ""),
    };
    if path.contains(';') {
        let from = path.rfind('/').unwrap_or(0);
        if let Some(j) = path[from..].find(';') {
            path = &path[..from + j];
        }
    }
    (path.to_string(), query.to_string())
}

/// urllib.parse.unquote_plus for one name or value (UTF-8, invalid bytes replaced).
pub fn unquote_plus(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        match b[i] {
            b'+' => out.push(b' '),
            b'%' if i + 2 < b.len() => {
                match (hex(b[i + 1]), hex(b[i + 2])) {
                    (Some(h), Some(l)) => {
                        out.push(h * 16 + l);
                        i += 3;
                        continue;
                    }
                    _ => out.push(b'%'),
                }
            }
            c => out.push(c),
        }
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn hex(c: u8) -> Option<u8> {
    (c as char).to_digit(16).map(|d| d as u8)
}

pub struct TooManyFields;

/// urllib.parse.parse_qsl(qs, keep_blank_values, max_num_fields): ordered (name, value) pairs.
pub fn parse_qsl(qs: &str, keep_blank: bool, max_fields: Option<usize>) -> Result<Vec<(String, String)>, TooManyFields> {
    if let Some(max) = max_fields {
        if 1 + qs.matches('&').count() > max {
            return Err(TooManyFields);
        }
    }
    let mut out = Vec::new();
    for nv in qs.split('&') {
        if nv.is_empty() {
            continue;
        }
        let (name, value) = match nv.split_once('=') {
            Some((n, v)) => (n, v),
            None if keep_blank => (nv, ""),
            None => continue,
        };
        if !value.is_empty() || keep_blank {
            out.push((unquote_plus(name), unquote_plus(value)));
        }
    }
    Ok(out)
}

/// First value of `name` the way `parse_qs(q).get(name, [default])[0]` reads it.
pub fn qs_first(qs: &str, name: &str) -> Option<String> {
    parse_qsl(qs, false, None).ok()?.into_iter().find(|(k, _)| k == name).map(|(_, v)| v)
}

/// Python int() on a decimal string: surrounding whitespace, sign, digit underscores.
pub fn py_int(s: &str) -> Option<i64> {
    let t = s.trim_matches(|c: char| c.is_ascii_whitespace());
    let (neg, digits) = match t.as_bytes().first() {
        Some(b'+') => (false, &t[1..]),
        Some(b'-') => (true, &t[1..]),
        _ => (false, t),
    };
    if digits.is_empty() || digits.starts_with('_') || digits.ends_with('_') || digits.contains("__") {
        return None;
    }
    let clean: String = digits.chars().filter(|&c| c != '_').collect();
    if !clean.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let v: i64 = clean.parse().ok()?;
    Some(if neg { -v } else { v })
}

/// Python str slicing by code points: `s[:n]`.
pub fn take_chars(s: &str, n: usize) -> &str {
    match s.char_indices().nth(n) {
        Some((i, _)) => &s[..i],
        None => s,
    }
}

pub struct Resp {
    pub status: u16,
    pub ctype: &'static str,
    pub body: Bytes,
    pub retry_after: Option<u32>,
    pub cors: bool,
    pub close: bool,
    pub error_log: Option<String>,
}

impl Resp {
    pub fn new(status: u16, ctype: &'static str, body: impl Into<Bytes>) -> Self {
        Resp { status, ctype, body: body.into(), retry_after: None, cors: false, close: false, error_log: None }
    }

    pub fn html(status: u16, body: impl Into<Bytes>) -> Self {
        Self::new(status, "text/html; charset=utf-8", body)
    }

    pub fn json(status: u16, body: impl Into<Bytes>) -> Self {
        Self::new(status, "application/json", body)
    }

    pub fn text(status: u16, body: impl Into<Bytes>) -> Self {
        Self::new(status, "text/plain", body)
    }

    pub fn retry_after(mut self, secs: u32) -> Self {
        self.retry_after = Some(secs);
        self
    }

    #[allow(dead_code)]
    pub fn cors(mut self) -> Self {
        self.cors = true;
        self
    }

    /// http.server's send_error page.
    pub fn error(code: u16, message: &str, explain: &str) -> Self {
        let body = format!(
            "<!DOCTYPE HTML>\n<html lang=\"en\">\n    <head>\n        <meta charset=\"utf-8\">\n        <title>Error response</title>\n    </head>\n    <body>\n        <h1>Error response</h1>\n        <p>Error code: {code}</p>\n        <p>Message: {}.</p>\n        <p>Error code explanation: {code} - {}.</p>\n    </body>\n</html>\n",
            html_escape(message, true),
            html_escape(explain, true)
        );
        let mut r = Self::new(code, "text/html;charset=utf-8", body);
        r.close = true;
        r.error_log = Some(format!("code {code}, message {message}"));
        r
    }

    pub fn not_found() -> Self {
        Self::error(404, "Not Found", "Nothing matches the given URI")
    }
}

/// html.escape(s, quote)
pub fn html_escape(s: &str, quote: bool) -> String {
    let mut o = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => o.push_str("&amp;"),
            '<' => o.push_str("&lt;"),
            '>' => o.push_str("&gt;"),
            '"' if quote => o.push_str("&quot;"),
            '\'' if quote => o.push_str("&#x27;"),
            c => o.push(c),
        }
    }
    o
}

pub fn log(peer: &str, msg: &str) {
    println!("{peer} - {msg}");
}

fn latin1(v: &HeaderValue) -> String {
    v.as_bytes().iter().map(|&b| b as char).collect()
}

fn version_str(v: hyper::Version) -> &'static str {
    match v {
        hyper::Version::HTTP_10 => "HTTP/1.0",
        hyper::Version::HTTP_09 => "HTTP/0.9",
        _ => "HTTP/1.1",
    }
}

fn to_response(r: Resp, head: bool) -> Response<Full<Bytes>> {
    let body = if head { Bytes::new() } else { r.body };
    let mut resp = Response::new(Full::new(body));
    *resp.status_mut() = StatusCode::from_u16(r.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    let h = resp.headers_mut();
    h.insert(CONTENT_TYPE, HeaderValue::from_static(r.ctype));
    if let Some(s) = r.retry_after {
        h.insert(RETRY_AFTER, HeaderValue::from(s));
    }
    if r.cors {
        h.insert("access-control-allow-origin", HeaderValue::from_static("*"));
    }
    if r.close {
        h.insert(CONNECTION, HeaderValue::from_static("close"));
    }
    resp
}

/// Accept loop: GET/POST go to `handler`, every other method gets 501 like http.server.
pub async fn serve<F, Fut>(listener: TcpListener, handler: F)
where
    F: Fn(Req) -> Fut + Clone + Send + Sync + 'static,
    Fut: Future<Output = Resp> + Send + 'static,
{
    let limit = Arc::new(Semaphore::new(MAX_CONNECTIONS));
    loop {
        let (stream, peer) = match listener.accept().await {
            Ok(x) => x,
            Err(_) => {
                tokio::time::sleep(Duration::from_millis(50)).await;
                continue;
            }
        };
        let Ok(permit) = limit.clone().acquire_owned().await else { return };
        let h = handler.clone();
        tokio::spawn(async move {
            let _permit = permit;
            let svc = service_fn(move |req: Request<Incoming>| {
                let h = h.clone();
                async move { Ok::<_, Infallible>(dispatch(req, peer, h).await) }
            });
            let _ = http1::Builder::new()
                .timer(TokioTimer::new())
                .header_read_timeout(HEADER_TIMEOUT)
                .serve_connection(TokioIo::new(stream), svc)
                .await;
        });
    }
}

async fn dispatch<F, Fut>(req: Request<Incoming>, peer: SocketAddr, h: F) -> Response<Full<Bytes>>
where
    F: Fn(Req) -> Fut,
    Fut: Future<Output = Resp>,
{
    let method = req.method().as_str().to_string();
    let target = req.uri().to_string();
    let ip = peer.ip().to_string();
    let line = format!("{method} {target} {}", version_str(req.version()));
    let headers = req.headers().iter().map(|(k, v)| (k.as_str().to_string(), latin1(v))).collect();
    let r = if method == "GET" || method == "POST" {
        h(Req::new(&method, &target, &ip, headers)).await
    } else {
        Resp::error(501, &format!("Unsupported method ('{method}')"), "Server does not support this operation")
    };
    if let Some(e) = &r.error_log {
        log(&ip, e);
    }
    log(&ip, &format!("\"{line}\" {} -", r.status));
    to_response(r, method == "HEAD")
}

/// `--health`: GET /status on the listen address, exit code for the Docker healthcheck.
pub fn health_check(bind: &str, port: u16) -> i32 {
    use std::io::{Read, Write};
    let host = if bind == "0.0.0.0" { "127.0.0.1" } else { bind };
    let addr: SocketAddr = match format!("{host}:{port}").parse() {
        Ok(a) => a,
        Err(_) => return 1,
    };
    let t = Duration::from_secs(3);
    let Ok(mut s) = std::net::TcpStream::connect_timeout(&addr, t) else { return 1 };
    let _ = s.set_read_timeout(Some(t));
    let _ = s.set_write_timeout(Some(t));
    if s.write_all(format!("GET /status HTTP/1.0\r\nHost: {host}:{port}\r\n\r\n").as_bytes()).is_err() {
        return 1;
    }
    let mut buf = [0u8; 16];
    let mut n = 0;
    while n < buf.len() {
        match s.read(&mut buf[n..]) {
            Ok(0) | Err(_) => break,
            Ok(k) => n += k,
        }
    }
    let head = String::from_utf8_lossy(&buf[..n]);
    if head.starts_with("HTTP/1.1 2") || head.starts_with("HTTP/1.0 2") { 0 } else { 1 }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn url_parts_like_urlparse() {
        assert_eq!(url_parts("/status?x=1"), ("/status".into(), "x=1".into()));
        assert_eq!(url_parts("/a/b;p=1?q#f"), ("/a/b".into(), "q".into()));
        assert_eq!(url_parts("http://h:1/gate?port=2"), ("/gate".into(), "port=2".into()));
        assert_eq!(url_parts("//status"), ("".into(), "".into()));
        assert_eq!(url_parts("/x#y?z"), ("/x".into(), "".into()));
    }

    #[test]
    fn route_strips_trailing_slashes() {
        let r = Req::new("GET", "/jf//", "1.2.3.4", vec![]);
        assert_eq!(r.route(), "/jf");
        assert_eq!(Req::new("GET", "/", "", vec![]).route(), "/");
    }

    #[test]
    fn qsl_like_python() {
        let v = parse_qsl("a=1&b=&c&&d=%41+x&a=2", true, None).ok().unwrap();
        assert_eq!(v, vec![("a".into(), "1".into()), ("b".into(), "".into()), ("c".into(), "".into()), ("d".into(), "A x".into()), ("a".into(), "2".into())]);
        let v = parse_qsl("a=1&b=&c", false, None).ok().unwrap();
        assert_eq!(v, vec![("a".into(), "1".into())]);
        assert!(parse_qsl(&"x&".repeat(50), true, Some(50)).is_err());
        assert_eq!(unquote_plus("%zz%4"), "%zz%4");
        assert_eq!(unquote_plus("%C3%A9%ff"), "\u{e9}\u{fffd}");
    }

    #[test]
    fn py_int_rules() {
        assert_eq!(py_int(" 8096 "), Some(8096));
        assert_eq!(py_int("+1_0"), Some(10));
        assert_eq!(py_int("-1"), Some(-1));
        assert_eq!(py_int(""), None);
        assert_eq!(py_int("1__0"), None);
        assert_eq!(py_int("0x10"), None);
        assert_eq!(py_int("99999999999999999999"), None);
    }

    #[test]
    fn take_chars_counts_code_points() {
        assert_eq!(take_chars("\u{e9}abc", 2), "\u{e9}a");
        assert_eq!(take_chars("ab", 5), "ab");
    }
}
