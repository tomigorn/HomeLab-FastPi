//! Tiny plain-HTTP client (copy of Beefy-Waker's): one connection per call, `Connection: close`, hard timeout, capped body.

use std::time::Duration;

use http_body_util::{BodyExt, Full};
use hyper::body::Bytes;
use hyper::client::conn::http1;
use hyper::Request;
use hyper_util::rt::TokioIo;
use tokio::net::TcpStream;

pub struct HttpResp {
    pub status: u16,
    pub body: Vec<u8>,
    /// true when the body was longer than the limit (body holds the first `limit` + 1 bytes)
    pub truncated: bool,
    pub etag: Option<String>,
}

/// `http://host[:port][/base]` with trailing slashes removed (urllib-style base URL from env).
#[derive(Clone, Debug, PartialEq)]
pub struct BaseUrl {
    pub host: String,
    pub port: u16,
    pub base: String,
}

impl BaseUrl {
    pub fn parse(url: &str) -> Option<BaseUrl> {
        let rest = url.trim_end_matches('/');
        let rest = rest.strip_prefix("http://").or_else(|| rest.strip_prefix("HTTP://"))?;
        let (hostport, base) = match rest.find('/') {
            Some(i) => (&rest[..i], &rest[i..]),
            None => (rest, ""),
        };
        let (host, port) = match hostport.rsplit_once(':') {
            Some((h, p)) => (h, p.parse().ok()?),
            None => (hostport, 80),
        };
        if host.is_empty() {
            return None;
        }
        Some(BaseUrl { host: host.to_string(), port, base: base.to_string() })
    }
}

#[allow(clippy::too_many_arguments)]
pub async fn request(
    method: &str,
    host: &str,
    port: u16,
    path: &str,
    headers: &[(&str, &str)],
    body: Option<Vec<u8>>,
    limit: usize,
    timeout: Duration,
) -> Result<HttpResp, String> {
    match tokio::time::timeout(timeout, request_inner(method, host, port, path, headers, body, limit)).await {
        Ok(r) => r,
        Err(_) => Err("timed out".into()),
    }
}

async fn request_inner(
    method: &str,
    host: &str,
    port: u16,
    path: &str,
    headers: &[(&str, &str)],
    body: Option<Vec<u8>>,
    limit: usize,
) -> Result<HttpResp, String> {
    let tcp = TcpStream::connect((host, port)).await.map_err(|e| e.to_string())?;
    let (mut sender, conn) = http1::handshake(TokioIo::new(tcp)).await.map_err(|e| e.to_string())?;
    // dropped with this future (also on the caller's timeout): the connection task ends and the socket closes
    let _conn = AbortOnDrop(tokio::spawn(async move {
        let _ = conn.await;
    }));
    let host_header = if port == 80 { host.to_string() } else { format!("{host}:{port}") };
    let mut b = Request::builder()
        .method(method)
        .uri(path)
        .header("host", host_header)
        .header("user-agent", "activity")
        .header("connection", "close");
    for (k, v) in headers {
        b = b.header(*k, *v);
    }
    let req = b.body(Full::new(Bytes::from(body.unwrap_or_default()))).map_err(|e| e.to_string())?;
    let resp = sender.send_request(req).await.map_err(|e| e.to_string())?;
    let status = resp.status().as_u16();
    let etag = resp.headers().get("etag").and_then(|v| v.to_str().ok()).map(str::to_string);
    let mut body = resp.into_body();
    let mut out = Vec::new();
    let mut truncated = false;
    while let Some(frame) = body.frame().await {
        let frame = frame.map_err(|e| e.to_string())?;
        if let Ok(data) = frame.into_data() {
            out.extend_from_slice(&data);
            if out.len() > limit {
                out.truncate(limit + 1);
                truncated = true;
                break;
            }
        }
    }
    Ok(HttpResp { status, body: out, truncated, etag })
}

struct AbortOnDrop(tokio::task::JoinHandle<()>);

impl Drop for AbortOnDrop {
    fn drop(&mut self) {
        self.0.abort();
    }
}

/// GET `base + path`: the body of a 200 answer within `limit` bytes, else a short reason (status, size, network error; never the body).
pub async fn get(base: &BaseUrl, path: &str, headers: &[(&str, &str)], limit: usize, timeout: Duration) -> Result<Vec<u8>, String> {
    let r = request("GET", &base.host, base.port, &format!("{}{path}", base.base), headers, None, limit, timeout).await?;
    if r.status != 200 {
        return Err(format!("HTTP {}", r.status));
    }
    if r.truncated {
        return Err(format!("answer over {limit} bytes"));
    }
    Ok(r.body)
}

#[derive(Debug, PartialEq)]
pub enum Cond {
    NotModified,
    /// the body and its ETag, if the server sent one
    Body(Vec<u8>, Option<String>),
}

/// GET with `If-None-Match: etag` when one is known: 304 = unchanged, else as `get`.
pub async fn get_cond(base: &BaseUrl, path: &str, headers: &[(&str, &str)], etag: Option<&str>, limit: usize, timeout: Duration) -> Result<Cond, String> {
    let mut h = headers.to_vec();
    if let Some(e) = etag {
        h.push(("if-none-match", e));
    }
    let r = request("GET", &base.host, base.port, &format!("{}{path}", base.base), &h, None, limit, timeout).await?;
    match r.status {
        304 if etag.is_some() => Ok(Cond::NotModified),
        200 if r.truncated => Err(format!("answer over {limit} bytes")),
        200 => Ok(Cond::Body(r.body, r.etag)),
        s => Err(format!("HTTP {s}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base_urls() {
        assert_eq!(BaseUrl::parse("http://192.168.1.152"), Some(BaseUrl { host: "192.168.1.152".into(), port: 80, base: "".into() }));
        assert_eq!(BaseUrl::parse("http://127.0.0.1:9093/"), Some(BaseUrl { host: "127.0.0.1".into(), port: 9093, base: "".into() }));
        assert_eq!(BaseUrl::parse("http://h:1/am//"), Some(BaseUrl { host: "h".into(), port: 1, base: "/am".into() }));
        assert_eq!(BaseUrl::parse("https://h"), None);
        assert_eq!(BaseUrl::parse("http://h:x"), None);
    }

    #[tokio::test]
    async fn a_timeout_closes_the_connection() {
        use tokio::io::AsyncReadExt;
        let l = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = l.local_addr().unwrap().port();
        let srv = tokio::spawn(async move {
            let (mut s, _) = l.accept().await.unwrap();
            let mut buf = vec![0u8; 4096];
            let mut n = 0;
            // read the request, never answer; return once the client closes
            loop {
                match tokio::time::timeout(Duration::from_secs(5), s.read(&mut buf[n..])).await {
                    Ok(Ok(0)) => return true,
                    Ok(Ok(k)) => n = (n + k).min(4000),
                    _ => return false,
                }
            }
        });
        let base = BaseUrl::parse(&format!("http://127.0.0.1:{port}")).unwrap();
        assert_eq!(get(&base, "/x", &[], 100, Duration::from_millis(300)).await, Err("timed out".into()));
        assert!(srv.await.unwrap(), "the socket is closed at the timeout, not left open");
    }

    /// One-shot server: answers 200 with an ETag, or 304 when the request carries that ETag in If-None-Match.
    async fn etag_server() -> (u16, tokio::task::JoinHandle<Vec<String>>) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let l = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = l.local_addr().unwrap().port();
        let h = tokio::spawn(async move {
            let mut seen = Vec::new();
            for _ in 0..2 {
                let (mut s, _) = l.accept().await.unwrap();
                let mut buf = vec![0u8; 4096];
                let n = s.read(&mut buf).await.unwrap();
                let req = String::from_utf8_lossy(&buf[..n]).to_lowercase();
                let resp = if req.contains("\r\nif-none-match: \"abc\"\r\n") {
                    "HTTP/1.1 304 Not Modified\r\nETag: \"abc\"\r\nConnection: close\r\n\r\n".to_string()
                } else {
                    "HTTP/1.1 200 OK\r\nETag: \"abc\"\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}".to_string()
                };
                seen.push(req);
                s.write_all(resp.as_bytes()).await.unwrap();
            }
            seen
        });
        (port, h)
    }

    #[tokio::test]
    async fn conditional_get_uses_the_etag() {
        let (port, srv) = etag_server().await;
        let base = BaseUrl::parse(&format!("http://127.0.0.1:{port}")).unwrap();
        let t = Duration::from_secs(2);
        assert_eq!(get_cond(&base, "/f", &[], None, 100, t).await, Ok(Cond::Body(b"{}".to_vec(), Some("\"abc\"".into()))));
        assert_eq!(get_cond(&base, "/f", &[], Some("\"abc\""), 100, t).await, Ok(Cond::NotModified));
        let seen = srv.await.unwrap();
        assert!(!seen[0].contains("if-none-match"), "{}", seen[0]);
    }
}
