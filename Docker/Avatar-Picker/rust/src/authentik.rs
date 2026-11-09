//! Minimal Authentik REST client: users list/get/patch with the API token, users/me with only the browser's session cookie.

use std::fmt;
use std::time::Duration;

use bytes::Bytes;
use http_body_util::{BodyExt, Full};
use hyper::{Method, Request, StatusCode};
use hyper_util::client::legacy::{connect::HttpConnector, Client as HyperClient};
use hyper_util::rt::TokioExecutor;
use serde_json::Value;

const MAX_PAGES: i64 = 100;
const MAX_BODY: usize = 16 * 1024 * 1024;

#[derive(Debug)]
pub struct AuthentikError(pub String);

impl fmt::Display for AuthentikError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

type Https = hyper_rustls::HttpsConnector<HttpConnector>;

pub struct Client {
    base: String,
    token: String,
    timeout: Duration,
    http: HyperClient<Https, Full<Bytes>>,
}

impl Client {
    /// Plain http only with allow_http (AUTHENTIK_ALLOW_HTTP=1, test and dev only): the token would travel in clear.
    pub fn new(base: &str, token: &str, allow_http: bool) -> Result<Self, AuthentikError> {
        let scheme = base.parse::<hyper::Uri>().ok().and_then(|u| u.scheme_str().map(str::to_ascii_lowercase));
        match scheme.as_deref() {
            Some("https") => {}
            Some("http") if allow_http => {}
            _ => return Err(AuthentikError(format!("AUTHENTIK_URL must be https:// (plain http only with AUTHENTIK_ALLOW_HTTP=1): {base:?}"))),
        }
        let mut tcp = HttpConnector::new();
        tcp.enforce_http(false);
        tcp.set_connect_timeout(Some(Duration::from_secs(10)));
        let builder = hyper_rustls::HttpsConnectorBuilder::new().with_webpki_roots();
        let builder = if allow_http { builder.https_or_http() } else { builder.https_only() };
        let https = builder.enable_http1().wrap_connector(tcp);
        let http = HyperClient::builder(TokioExecutor::new()).pool_idle_timeout(Duration::from_secs(30)).build(https);
        Ok(Client { base: base.trim_end_matches('/').to_string(), token: token.to_string(), timeout: Duration::from_secs(10), http })
    }

    async fn send(&self, req: Request<Full<Bytes>>) -> Result<(StatusCode, Bytes), String> {
        let fut = async {
            let resp = self.http.request(req).await.map_err(|e| format!("{e}"))?;
            let status = resp.status();
            let body = http_body_util::Limited::new(resp.into_body(), MAX_BODY).collect().await.map_err(|e| format!("{e}"))?.to_bytes();
            Ok((status, body))
        };
        tokio::time::timeout(self.timeout, fut).await.map_err(|_| "timed out".to_string())?
    }

    pub async fn call(&self, method: Method, path: &str, body: Option<Value>) -> Result<Value, AuthentikError> {
        let what = format!("{method} {path}");
        let data = body.map(|b| Bytes::from(b.to_string())).unwrap_or_default();
        let req = Request::builder()
            .method(method)
            .uri(format!("{}{path}", self.base))
            .header("Authorization", format!("Bearer {}", self.token))
            .header("Accept", "application/json")
            .header("Content-Type", "application/json")
            .body(Full::new(data))
            .map_err(|e| AuthentikError(format!("{what}: {e}")))?;
        let (status, body) = self.send(req).await.map_err(|e| AuthentikError(format!("{what}: {e}")))?;
        if !status.is_success() {
            return Err(AuthentikError(format!("{what}: HTTP {}", status.as_u16())));
        }
        if body.is_empty() {
            return Ok(Value::Object(Default::default()));
        }
        serde_json::from_slice(&body).map_err(|e| AuthentikError(format!("{what}: {e}")))
    }

    /// All human users (service accounts excluded).
    pub async fn list_users(&self) -> Result<Vec<Value>, AuthentikError> {
        let mut users = Vec::new();
        let mut page = 1i64;
        while page > 0 {
            let data = self.call(Method::GET, &format!("/api/v3/core/users/?page={page}&page_size=100"), None).await?;
            if let Some(results) = data.get("results").and_then(Value::as_array) {
                users.extend(results.iter().filter(|u| matches!(u.get("type").and_then(Value::as_str), Some("internal" | "external"))).cloned());
            }
            let next = data.get("pagination").and_then(|p| p.get("next")).and_then(Value::as_i64).unwrap_or(0);
            page = if next > page && next <= MAX_PAGES { next } else { 0 };
        }
        Ok(users)
    }

    pub async fn get_user(&self, pk: i64) -> Result<Value, AuthentikError> {
        self.call(Method::GET, &format!("/api/v3/core/users/{pk}/"), None).await
    }

    pub async fn set_attributes(&self, pk: i64, attributes: Value) -> Result<(), AuthentikError> {
        self.call(Method::PATCH, &format!("/api/v3/core/users/{pk}/"), Some(serde_json::json!({"attributes": attributes}))).await.map(|_| ())
    }

    /// Is this authentik_session cookie a live login? Never sends our token, never follows redirects.
    pub async fn session_valid(&self, cookie: &str) -> Result<bool, AuthentikError> {
        if cookie.is_empty() {
            return Ok(false);
        }
        let req = Request::builder()
            .method(Method::GET)
            .uri(format!("{}/api/v3/core/users/me/", self.base))
            .header("Cookie", format!("authentik_session={cookie}"))
            .header("Accept", "application/json")
            .body(Full::new(Bytes::new()));
        let Ok(req) = req else { return Ok(false) };
        match self.send(req).await {
            Ok((status, _)) => match status.as_u16() {
                200 => Ok(true),
                201..=299 | 301 | 302 | 303 | 307 | 308 | 401 | 403 => Ok(false),
                code => Err(AuthentikError(format!("GET users/me: HTTP {code}"))),
            },
            Err(_) => Err(AuthentikError("GET users/me: unreachable".into())),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn https_accepted() {
        assert!(Client::new("https://sso.example.com", "t", false).is_ok());
        assert!(Client::new("HTTPS://sso.example.com/", "t", false).is_ok());
    }

    #[test]
    fn plain_http_refused_by_default() {
        let err = Client::new("http://sso.example.com", "t", false).err().expect("http accepted");
        assert!(err.0.contains("https"), "{err}");
        assert!(Client::new("sso.example.com", "t", false).is_err());
        assert!(Client::new("", "t", false).is_err());
    }

    #[test]
    fn plain_http_only_with_dev_flag() {
        assert!(Client::new("http://127.0.0.1:9999", "t", true).is_ok());
        assert!(Client::new("ftp://127.0.0.1:9999", "t", true).is_err());
    }
}
