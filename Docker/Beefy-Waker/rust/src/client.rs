//! Tiny plain-HTTP client for LAN calls (Jellyfin, myStrom, Alertmanager): one connection per call, hard timeout, capped body.

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
    tokio::spawn(async move {
        let _ = conn.await;
    });
    let host_header = if port == 80 { host.to_string() } else { format!("{host}:{port}") };
    let mut b = Request::builder()
        .method(method)
        .uri(path)
        .header("host", host_header)
        .header("user-agent", "waker")
        .header("connection", "close");
    for (k, v) in headers {
        b = b.header(*k, *v);
    }
    let req = b.body(Full::new(Bytes::from(body.unwrap_or_default()))).map_err(|e| e.to_string())?;
    let resp = sender.send_request(req).await.map_err(|e| e.to_string())?;
    let status = resp.status().as_u16();
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
    Ok(HttpResp { status, body: out, truncated })
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
}
