//! qBittorrent, Audiobookshelf, AudioBookRequest, Prowlarr and Audible over HTTP. Every call has a timeout.
use crate::config::{secret, Config};
use crate::naming::Book;
use crate::util::{percent_encode_path, str_of, truthy, Result};
use bytes::Bytes;
use reqwest::cookie::{CookieStore, Jar};
use reqwest::header::{HeaderMap, HeaderName, HeaderValue, AUTHORIZATION, CONTENT_TYPE, REFERER};
use reqwest::{Client, Method, StatusCode, Url};
use serde_json::{json, Map, Value};
use std::fmt;
use std::sync::Arc;
use std::time::Duration;

pub const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
pub const DEFAULT_TIMEOUT: Duration = Duration::from_secs(30);

/// A non-2xx answer, like urllib's HTTPError: callers decide whether it is an error.
#[derive(Debug)]
pub struct HttpError {
    pub status: u16,
}

impl fmt::Display for HttpError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "HTTP {}", self.status)
    }
}

impl std::error::Error for HttpError {}

pub fn http_status(e: &crate::util::Error) -> Option<u16> {
    e.downcast_ref::<HttpError>().map(|h| h.status)
}

pub fn new_client() -> Client {
    Client::builder().connect_timeout(CONNECT_TIMEOUT).timeout(DEFAULT_TIMEOUT).build().expect("http client")
}

pub fn headers(pairs: &[(&str, &str)]) -> HeaderMap {
    let mut h = HeaderMap::new();
    for (k, v) in pairs {
        if let (Ok(name), Ok(value)) = (HeaderName::from_bytes(k.as_bytes()), HeaderValue::from_str(v)) {
            h.insert(name, value);
        }
    }
    h
}

/// Status, content type and body of any answer; only transport failures are errors.
pub async fn fetch(client: &Client, method: Method, url: &str, headers: HeaderMap, body: Option<Bytes>, timeout: Duration) -> Result<(StatusCode, String, Bytes)> {
    let mut req = client.request(method, url).headers(headers).timeout(timeout);
    if let Some(b) = body {
        req = req.body(b);
    }
    let resp = req.send().await?;
    let status = resp.status();
    let ctype = resp.headers().get(CONTENT_TYPE).and_then(|v| v.to_str().ok()).unwrap_or("").to_string();
    let bytes = resp.bytes().await?;
    Ok((status, ctype, bytes))
}

/// http_json: parsed JSON of a 2xx answer (Null when empty), HttpError otherwise.
pub async fn fetch_json(client: &Client, method: Method, url: &str, headers: HeaderMap, body: Option<Bytes>, timeout: Duration) -> Result<Value> {
    let (status, _, bytes) = fetch(client, method, url, headers, body, timeout).await?;
    if !status.is_success() {
        return Err(Box::new(HttpError { status: status.as_u16() }));
    }
    if bytes.iter().all(|b| b.is_ascii_whitespace()) {
        return Ok(Value::Null);
    }
    Ok(serde_json::from_slice(&bytes)?)
}

pub fn bearer(key: &str) -> HeaderMap {
    headers(&[("Authorization", &format!("Bearer {key}"))])
}

pub struct Qbit {
    cfg: Arc<Config>,
    password: String,
    client: Client,
    jar: Arc<Jar>,
    logged_in: tokio::sync::Mutex<bool>,
}

impl Qbit {
    pub fn new(cfg: Arc<Config>, password: String) -> Qbit {
        let jar = Arc::new(Jar::default());
        let client = Client::builder().cookie_provider(jar.clone()).connect_timeout(CONNECT_TIMEOUT).timeout(DEFAULT_TIMEOUT).build().expect("http client");
        Qbit { cfg, password, client, jar, logged_in: tokio::sync::Mutex::new(false) }
    }

    fn base(&self) -> Result<Url> {
        Ok(Url::parse(&self.cfg.qbit_url)?)
    }

    async fn login(&self) -> Result<()> {
        let base = self.base()?;
        self.jar.add_cookie_str("SID=; Max-Age=0", &base);
        let resp = self
            .client
            .post(format!("{}/api/v2/auth/login", self.cfg.qbit_url))
            .header(REFERER, &self.cfg.qbit_url)
            .form(&[("username", self.cfg.qbit_user.as_str()), ("password", self.password.as_str())])
            .send()
            .await?;
        let _ = resp.bytes().await?;
        let has_sid = self.jar.cookies(&base).and_then(|v| v.to_str().ok().map(|s| s.contains("SID"))).unwrap_or(false);
        if !has_sid {
            return Err("qBittorrent login failed".into());
        }
        Ok(())
    }

    /// GET with the session cookie; one re-login when the session is gone (403).
    async fn get(&self, path: &str) -> Result<(String, Bytes)> {
        for attempt in 1..=2 {
            {
                let mut li = self.logged_in.lock().await;
                if !*li {
                    self.login().await?;
                    *li = true;
                }
            }
            let resp = self.client.get(format!("{}{}", self.cfg.qbit_url, path)).header(REFERER, &self.cfg.qbit_url).send().await?;
            let status = resp.status();
            if status == StatusCode::FORBIDDEN {
                if attempt == 2 {
                    return Err(Box::new(HttpError { status: 403 }));
                }
                *self.logged_in.lock().await = false;
                continue;
            }
            let ctype = resp.headers().get(CONTENT_TYPE).and_then(|v| v.to_str().ok()).unwrap_or("").to_string();
            let bytes = resp.bytes().await?;
            if !status.is_success() {
                return Err(Box::new(HttpError { status: status.as_u16() }));
            }
            return Ok((ctype, bytes));
        }
        Err("qBittorrent unreachable".into())
    }

    async fn get_list(&self, path: &str) -> Result<Vec<Value>> {
        let (_, bytes) = self.get(path).await?;
        if bytes.iter().all(|b| b.is_ascii_whitespace()) {
            return Ok(vec![]);
        }
        Ok(serde_json::from_slice::<Value>(&bytes)?.as_array().cloned().unwrap_or_default())
    }

    pub async fn category(&self) -> Result<Vec<Value>> {
        self.get_list(&format!("/api/v2/torrents/info?category={}", self.cfg.category)).await
    }

    pub async fn torrent(&self, hash: &str) -> Result<Option<Value>> {
        Ok(self.get_list(&format!("/api/v2/torrents/info?hashes={hash}")).await?.into_iter().next())
    }

    pub async fn export(&self, hash: &str) -> Result<Bytes> {
        Ok(self.get(&format!("/api/v2/torrents/export?hash={hash}")).await?.1)
    }
}

pub const PROVIDERS: [(&str, &str, &str); 3] = [("com", "audible", "us"), ("de", "audible.de", "de"), ("co.uk", "audible.uk", "uk")];

pub fn provider(region: Option<&str>) -> (&'static str, &'static str) {
    let found = PROVIDERS.iter().find(|p| Some(p.0) == region).unwrap_or(&PROVIDERS[0]);
    (found.1, found.2)
}

pub fn match_body(book: &Book, asin: Option<&str>, region: Option<&str>) -> Value {
    let mut body = Map::new();
    body.insert("provider".into(), json!(provider(region).0));
    if let Some(a) = asin.filter(|a| !a.is_empty()) {
        body.insert("asin".into(), json!(a));
    }
    body.insert("title".into(), json!(book.title));
    body.insert("author".into(), json!(book.authors.first().cloned().unwrap_or_default()));
    body.insert("overrideCover".into(), json!(true));
    body.insert("overrideDetails".into(), json!(true));
    Value::Object(body)
}

pub fn author_match_body(name: &str, region: Option<&str>) -> Value {
    json!({"q": name, "region": provider(region).1})
}

/// Audible lists one author under several ASINs, often only one with a picture: the other ASINs of the same name, in order.
pub fn other_author_asins(found: &[Value], name: &str, current: Option<&str>) -> Vec<String> {
    let key = |n: &str| n.to_lowercase().split_whitespace().collect::<Vec<_>>().join(" ");
    let mut out: Vec<String> = vec![];
    for a in found {
        let asin = str_of(a.get("asin")).unwrap_or("");
        if key(str_of(a.get("name")).unwrap_or("")) == key(name) && !asin.is_empty() && Some(asin) != current && !out.iter().any(|o| o == asin) {
            out.push(asin.to_string());
        }
    }
    out
}

pub fn merge_searches(results: &[Value]) -> Value {
    let books: Vec<Value> = results.iter().flat_map(|r| r.get("book").and_then(Value::as_array).cloned().unwrap_or_default()).collect();
    json!({"book": books})
}

/// ABS has one library per language folder (/audiobooks/EN, /DE, /Other).
pub fn library_for(libs: &[Value], path: &str) -> Option<String> {
    for lib in libs {
        let folders = lib.get("folders").and_then(Value::as_array);
        if folders.is_some_and(|fs| fs.iter().any(|f| str_of(f.get("fullPath")).is_some_and(|p| path.starts_with(&format!("{}/", p.trim_end_matches('/')))))) {
            return str_of(lib.get("id")).map(String::from);
        }
    }
    None
}

pub struct Abs {
    cfg: Arc<Config>,
    client: Client,
}

impl Abs {
    pub fn new(cfg: Arc<Config>, client: Client) -> Abs {
        Abs { cfg, client }
    }

    pub fn key(&self) -> String {
        secret(&self.cfg.abs_key_file)
    }

    fn auth(&self) -> HeaderMap {
        bearer(&self.key())
    }

    pub async fn get(&self, path: &str, timeout: Duration) -> Result<Value> {
        fetch_json(&self.client, Method::GET, &format!("{}{}", self.cfg.abs_url, path), self.auth(), None, timeout).await
    }

    pub async fn post(&self, path: &str, body: &Value) -> Result<Value> {
        let mut h = self.auth();
        h.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        fetch_json(&self.client, Method::POST, &format!("{}{}", self.cfg.abs_url, path), h, Some(Bytes::from(serde_json::to_vec(body)?)), DEFAULT_TIMEOUT).await
    }

    pub async fn libraries(&self) -> Result<Vec<Value>> {
        let v = self.get("/api/libraries", DEFAULT_TIMEOUT).await?;
        v.get("libraries").and_then(Value::as_array).cloned().ok_or_else(|| "ABS /api/libraries without libraries".into())
    }

    pub async fn items(&self, lib: &str) -> Result<Vec<Value>> {
        let v = self.get(&format!("/api/libraries/{lib}/items?minified=1"), Duration::from_secs(60)).await?;
        Ok(v.get("results").and_then(Value::as_array).cloned().unwrap_or_default())
    }

    pub async fn users(&self) -> Result<Vec<Value>> {
        let v = self.get("/api/users", DEFAULT_TIMEOUT).await?;
        Ok(v.get("users").and_then(Value::as_array).cloned().unwrap_or_default())
    }

    pub async fn cover(&self, item: &str) -> Result<(String, Bytes)> {
        let (status, ctype, bytes) = fetch(&self.client, Method::GET, &format!("{}/api/items/{item}/cover?width=240&format=webp", self.cfg.abs_url), self.auth(), None, DEFAULT_TIMEOUT).await?;
        if !status.is_success() {
            return Err(Box::new(HttpError { status: status.as_u16() }));
        }
        Ok((if ctype.is_empty() { "image/webp".to_string() } else { ctype }, bytes))
    }

    pub async fn library(&self, rel: &str) -> Result<String> {
        let path = self.cfg.abs_path(rel);
        library_for(&self.libraries().await?, &path).ok_or_else(|| format!("no ABS library holds {path}").into())
    }

    pub async fn find_item(&self, rel: &str, title: &str) -> Result<Option<String>> {
        let lib = self.library(rel).await?;
        let found = self.get(&format!("/api/libraries/{lib}/search?q={}&limit=25", percent_encode_path(title)), DEFAULT_TIMEOUT).await?;
        let path = self.cfg.abs_path(rel);
        for hit in found.get("book").and_then(Value::as_array).into_iter().flatten() {
            let item = hit.get("libraryItem");
            if item.and_then(|i| str_of(i.get("path"))) == Some(path.as_str()) {
                return Ok(item.and_then(|i| str_of(i.get("id"))).map(String::from));
            }
        }
        Ok(None)
    }

    /// Audible match (details + cover), then every author (image + description). Returns false until ABS has the item.
    pub async fn match_job(&self, job: &Value) -> Result<bool> {
        let dest = str_of(job.get("dest")).unwrap_or("");
        let b = job.get("book").cloned().unwrap_or_else(|| json!({}));
        let authors: Vec<String> = b.get("authors").and_then(Value::as_array).map(|a| a.iter().filter_map(Value::as_str).map(String::from).collect()).unwrap_or_default();
        let book = Book::new(str_of(b.get("title")).unwrap_or(""), authors, None, None, "EN");
        let Some(item_id) = self.find_item(dest, &book.title).await? else { return Ok(false) };
        let region = str_of(job.get("region"));
        let result = self.post(&format!("/api/items/{item_id}/match"), &match_body(&book, str_of(job.get("asin")), region)).await?;
        if let Some(w) = result.get("warning").filter(|w| truthy(Some(w))) {
            log::warn!("ABS match {dest}: {w}");
        }
        let item = self.get(&format!("/api/items/{item_id}"), DEFAULT_TIMEOUT).await?;
        let authors = item.pointer("/media/metadata/authors").and_then(Value::as_array).cloned().unwrap_or_default();
        for author in &authors {
            if let Err(e) = self.match_author(author, region).await {
                match http_status(&e) {
                    Some(code) => log::warn!("ABS author match {}: HTTP {code}", str_of(author.get("name")).unwrap_or("")),
                    None => return Err(e),
                }
            }
        }
        log::info!("ABS matched {dest}");
        Ok(true)
    }

    async fn match_author(&self, author: &Value, region: Option<&str>) -> Result<()> {
        let name = str_of(author.get("name")).unwrap_or("");
        let id = str_of(author.get("id")).unwrap_or("");
        let body = author_match_body(name, region);
        let region_code = provider(region).1;
        let author_of = |v: Value| v.get("author").cloned().unwrap_or_else(|| json!({}));
        let mut found = author_of(self.post(&format!("/api/authors/{id}/match"), &body).await?);
        if truthy(found.get("imagePath")) {
            return Ok(());
        }
        let q = form_urlencoded::Serializer::new(String::new()).append_pair("name", name).append_pair("region", region_code).finish();
        let mut best = if truthy(found.get("description")) { Some(found.clone()) } else { None };
        let candidates = match fetch_json(&self.client, Method::GET, &format!("{}/authors?{q}", self.cfg.audnexus_url), HeaderMap::new(), None, DEFAULT_TIMEOUT).await {
            Ok(v) => v.as_array().cloned().unwrap_or_default(),
            Err(e) => {
                log::warn!("audnexus author search {name}: {e}");
                vec![]
            }
        };
        let current = str_of(found.get("asin")).map(String::from);
        for asin in other_author_asins(&candidates, name, current.as_deref()) {
            found = author_of(self.post(&format!("/api/authors/{id}/match"), &json!({"asin": asin, "region": region_code})).await?);
            if truthy(found.get("imagePath")) {
                log::info!("author image for {name} via {asin}");
                return Ok(());
            }
            if best.is_none() && truthy(found.get("description")) {
                best = Some(found.clone());
            }
        }
        if let Some(b) = &best {
            if b.get("asin") != found.get("asin") {
                self.post(&format!("/api/authors/{id}/match"), &json!({"asin": b.get("asin").cloned().unwrap_or(Value::Null), "region": region_code})).await?;
            }
        }
        log::info!("no author image on Audible for {name} (kept {})", str_of(best.as_ref().unwrap_or(&found).get("asin")).unwrap_or(""));
        Ok(())
    }

    pub async fn scan(&self, rel: &str) -> Result<()> {
        let lib = self.library(rel).await?;
        fetch_json(&self.client, Method::POST, &format!("{}/api/libraries/{lib}/scan", self.cfg.abs_url), self.auth(), Some(Bytes::new()), Duration::from_secs(60)).await?;
        log::info!("ABS library scan started");
        Ok(())
    }
}

/// The Audible product of an ASIN and the region it was found in.
pub async fn audible(cfg: &Config, client: &Client, asin: Option<&str>) -> (Option<Value>, Option<String>) {
    let Some(asin) = asin else { return (None, None) };
    if asin.len() != 10 || !asin.chars().all(|c| c.is_ascii_digit() || c.is_ascii_uppercase()) {
        return (None, None);
    }
    for region in &cfg.audible_regions {
        let url = format!("{}.{region}/1.0/catalog/products/{asin}?response_groups=series,contributors,product_desc,product_attrs,product_extended_attrs", cfg.audible_base);
        match fetch_json(client, Method::GET, &url, HeaderMap::new(), None, DEFAULT_TIMEOUT).await {
            Ok(v) => {
                let product = v.get("product").cloned().unwrap_or_else(|| json!({}));
                if truthy(product.get("title")) {
                    return (Some(product), Some(region.clone()));
                }
            }
            Err(e) => log::warn!("audible {region} {asin}: {e}"),
        }
    }
    (None, None)
}

/// Prowlarr pass-through call: status, body and content type of whatever Prowlarr answers.
pub async fn prowlarr(cfg: &Config, client: &Client, method: Method, path: &str, headers: HeaderMap, data: Option<Bytes>) -> Result<(u16, Bytes, String)> {
    let (status, ctype, bytes) = fetch(client, method, &format!("{}{path}", cfg.prowlarr_url), headers, data, Duration::from_secs(120)).await?;
    let ctype = if ctype.is_empty() { if status.is_success() { "application/json" } else { "text/plain" }.to_string() } else { ctype };
    Ok((status.as_u16(), bytes, ctype))
}

pub async fn abr_json(cfg: &Config, client: &Client, path: &str, key: &str) -> Result<Value> {
    fetch_json(client, Method::GET, &format!("{}{path}", cfg.abr_url), bearer(key), None, DEFAULT_TIMEOUT).await
}

pub fn authorization(h: &HeaderMap) -> String {
    h.get(AUTHORIZATION).and_then(|v| v.to_str().ok()).unwrap_or("").to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn match_bodies() {
        let book = Book::new("The Final Empire", vec!["Brandon Sanderson".into(), "X".into()], Some("Mistborn".into()), Some("1".into()), "EN");
        assert_eq!(match_body(&book, Some("B002UZMLXM"), Some("com")), json!({"provider": "audible", "asin": "B002UZMLXM", "title": "The Final Empire",
            "author": "Brandon Sanderson", "overrideCover": true, "overrideDetails": true}));
        let t = Book::new("T", vec!["A".into()], None, None, "EN");
        assert_eq!(match_body(&t, Some("B000000001"), Some("de"))["provider"], "audible.de");
        assert_eq!(match_body(&t, Some("B000000001"), Some("co.uk"))["provider"], "audible.uk");
        let body = match_body(&Book::new("Project Hail Mary", vec!["Andy Weir".into()], None, None, "EN"), None, None);
        assert_eq!(body["provider"], "audible");
        assert!(body.get("asin").is_none());
        assert_eq!(author_match_body("Brandon Sanderson", Some("de")), json!({"q": "Brandon Sanderson", "region": "de"}));
        assert_eq!(author_match_body("Andy Weir", None), json!({"q": "Andy Weir", "region": "us"}));
    }

    #[test]
    fn libraries_and_authors() {
        let libs = vec![json!({"id": "en", "folders": [{"fullPath": "/audiobooks/EN"}]}), json!({"id": "de", "folders": [{"fullPath": "/audiobooks/DE"}]}),
                        json!({"id": "other", "folders": [{"fullPath": "/audiobooks/Other"}]})];
        assert_eq!(library_for(&libs, "/audiobooks/DE/Jörg Müßig/T").as_deref(), Some("de"));
        assert_eq!(library_for(&libs, "/audiobooks/Other/A/T").as_deref(), Some("other"));
        assert_eq!(library_for(&libs[..1], "/audiobooks/ENX/A/T"), None);
        let found = vec![json!({"asin": "B1", "name": "Jane Doe"}), json!({"asin": "B1", "name": "Jane Doe"}), json!({"asin": "B2", "name": "Jane  Doe"}),
                         json!({"asin": "B3", "name": "John Doe"}), json!({"asin": "B4", "name": "jane doe"})];
        assert_eq!(other_author_asins(&found, "Jane Doe", Some("B2")), ["B1", "B4"]);
        let merged = merge_searches(&[json!({"book": [{"libraryItem": {"id": "1"}}], "series": []}), json!({"book": [{"libraryItem": {"id": "2"}}]}), json!({"book": []})]);
        assert_eq!(merged, json!({"book": [{"libraryItem": {"id": "1"}}, {"libraryItem": {"id": "2"}}]}));
    }
}
