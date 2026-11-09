//! The HTTP side: caller gate by peer address, webhook, quota, page data, ABS and Prowlarr pass-throughs.
use crate::app::App;
use crate::clients::{abr_json, authorization, http_status, merge_searches, prowlarr, HttpError};
use crate::config::{MAX_BODY, WEBHOOK_BODY};
use crate::library::{self, book_library_ids};
use crate::pipeline::{self, load, parse_webhook, save, snapshot_quota};
use crate::quota::{my_quota, quota_ok};
use crate::ranking::{for_abr, norm_name, release_authors};
use crate::util::{first_query, now, parse_qs, str_of, truthy, Result};
use axum::body::{to_bytes, Body};
use axum::extract::{ConnectInfo, Request, State};
use axum::http::{header, HeaderMap, HeaderValue, Method, StatusCode};
use axum::response::Response;
use bytes::Bytes;
use regex::Regex;
use serde_json::{json, Map, Value};
use std::collections::HashSet;
use std::net::SocketAddr;
use std::sync::{Arc, LazyLock};

/// Only these neighbours on traefik_mouse may call these paths (keys ending in / are prefixes): the username header is trusted only from books-proxy,
/// the .torrent carries the MAM passkey, webhook jobs and Prowlarr writes (the wedge setting) only from ABR.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Peer {
    BooksProxy,
    Abr,
}

pub const CALLERS: [(&str, Peer); 7] = [
    ("/quota", Peer::BooksProxy),
    ("/all-requests", Peer::BooksProxy),
    ("/my-quota", Peer::BooksProxy),
    ("/library", Peer::BooksProxy),
    ("/library-cover/", Peer::BooksProxy),
    ("/sizes", Peer::BooksProxy),
    ("/prowlarr/torrent", Peer::Abr),
];
pub const POST_CALLERS: [(&str, Peer); 2] = [("/abr", Peer::Abr), ("/prowlarr/", Peer::Abr)];

pub fn wanted_peer(path: &str, method: &Method) -> Option<Peer> {
    let table: &[(&str, Peer)] = if method == Method::POST { &POST_CALLERS } else { &CALLERS };
    table
        .iter()
        .find(|(k, _)| *k == path)
        .or_else(|| table.iter().find(|(k, _)| k.ends_with('/') && path.starts_with(k)))
        .map(|(_, p)| *p)
}

/// ABR also calls over the egress network, whose address is dynamic: names are resolved per call.
pub async fn caller_ok(app: &App, path: &str, client: &str, method: &Method) -> bool {
    let Some(peer) = wanted_peer(path, method) else { return true };
    match peer {
        Peer::BooksProxy => client == app.cfg.books_proxy_ip,
        Peer::Abr => {
            if client == app.cfg.abr_ip {
                return true;
            }
            let host = &app.cfg.abr_host;
            if host.is_empty() || host.starts_with(|c: char| c.is_ascii_digit()) {
                return false;
            }
            match tokio::net::lookup_host((host.as_str(), 0)).await {
                Ok(addrs) => addrs.map(|a| a.ip().to_string()).any(|ip| ip == client),
                Err(_) => false,
            }
        }
    }
}

fn respond(status: u16, ctype: &str, body: impl Into<Body>, extra: &[(&str, &str)]) -> Response {
    let mut r = Response::builder().status(status);
    if !ctype.is_empty() {
        r = r.header(header::CONTENT_TYPE, ctype);
    }
    for (k, v) in extra {
        r = r.header(*k, *v);
    }
    r.body(body.into()).unwrap_or_else(|_| Response::new(Body::empty()))
}

fn status(code: u16) -> Response {
    let text = StatusCode::from_u16(code).ok().and_then(|s| s.canonical_reason()).unwrap_or("");
    respond(code, "text/plain", format!("{code} {text}"), &[])
}

fn json_response(code: u16, value: &Value) -> Response {
    respond(code, "application/json", serde_json::to_vec(value).unwrap_or_default(), &[("Cache-Control", "no-store")])
}

fn username(headers: &HeaderMap) -> String {
    headers.get("x-authentik-username").and_then(|v| v.to_str().ok()).unwrap_or("").to_string()
}

pub async fn dispatch(State(app): State<Arc<App>>, ConnectInfo(addr): ConnectInfo<SocketAddr>, req: Request) -> Response {
    let method = req.method().clone();
    let path = req.uri().path().to_string();
    let path_and_query = req.uri().path_and_query().map(|p| p.as_str().to_string()).unwrap_or_else(|| path.clone());
    let client = addr.ip().to_string();
    if !caller_ok(&app, &path, &client, &method).await {
        return status(403);
    }
    let (parts, body) = req.into_parts();
    match method {
        Method::GET => get(&app, &path, &path_and_query, &parts.headers).await,
        Method::POST => post(&app, &path, &path_and_query, &parts.headers, body).await,
        _ => status(501),
    }
}

async fn get(app: &App, path: &str, path_and_query: &str, headers: &HeaderMap) -> Response {
    if path_and_query.starts_with("/prowlarr/") {
        return forward(app, Method::GET, path_and_query, headers, None).await;
    }
    if path_and_query.starts_with("/abs/") {
        return abs_forward(app, path_and_query, headers).await;
    }
    match path {
        "/all-requests" => all_requests_handler(app, headers).await,
        "/library" => library_handler(app, headers).await,
        _ if path.starts_with("/library-cover/") => cover_handler(app, path, headers).await,
        "/sizes" => sizes_handler(app, headers).await,
        "/quota" => quota_handler(app, headers).await,
        "/my-quota" => my_quota_handler(app, headers).await,
        "/health" => respond(200, "", "ok", &[]),
        _ => status(404),
    }
}

async fn post(app: &App, path: &str, path_and_query: &str, headers: &HeaderMap, body: Body) -> Response {
    let length: i64 = match headers.get(header::CONTENT_LENGTH) {
        Some(v) => match v.to_str().ok().and_then(|s| s.trim().parse().ok()) {
            Some(n) => n,
            None => return respond(400, "text/plain", "bad Content-Length", &[("Connection", "close")]),
        },
        None => 0,
    };
    if length < 0 {
        return respond(400, "text/plain", "bad Content-Length", &[("Connection", "close")]);
    }
    if length as usize > MAX_BODY {
        return respond(413, "text/plain", "413 Content Too Large", &[("Connection", "close")]);
    }
    if path_and_query.starts_with("/prowlarr/") {
        let data = match to_bytes(body, MAX_BODY).await {
            Ok(b) => b,
            Err(_) => return status(413),
        };
        return forward(app, Method::POST, path_and_query, headers, Some(data)).await;
    }
    if path != "/abr" {
        return status(404);
    }
    let data = match to_bytes(body, WEBHOOK_BODY).await {
        Ok(b) => b,
        Err(_) => return respond(400, "text/plain", "body too large", &[]),
    };
    let parsed: Value = match serde_json::from_slice(&data) {
        Ok(v) => v,
        Err(e) => return respond(400, "text/plain", e.to_string(), &[]),
    };
    let job = match parse_webhook(&parsed) {
        Ok(j) => j,
        Err(e) => return respond(400, "text/plain", e, &[]),
    };
    {
        let _guard = app.jobs_lock.lock().await;
        let mut jobs = match load(&app.cfg.state) {
            Ok(j) => j,
            Err(e) => {
                log::error!("jobs: {e}");
                return status(500);
            }
        };
        let key = match str_of(job.get("hash")) {
            Some(h) => h.to_string(),
            None => format!("unbound-{:.0}", job.get("added").and_then(Value::as_f64).unwrap_or(0.0)),
        };
        if !jobs.contains_key(&key) {
            jobs.insert(key, job.clone());
            if let Err(e) = save(&app.cfg.state, &jobs) {
                log::error!("save jobs: {e}");
                return status(500);
            }
        }
    }
    let shown = str_of(job.get("hash")).unwrap_or("unbound");
    log::info!("queued {} {}", &shown[..8.min(shown.len())], str_of(job.get("title")).unwrap_or(""));
    respond(204, "", Body::empty(), &[])
}

fn pass_headers(headers: &HeaderMap) -> HeaderMap {
    let mut out = HeaderMap::new();
    for name in ["x-api-key", "content-type", "accept", "user-agent"] {
        if let Some(v) = headers.get(name) {
            out.insert(header::HeaderName::from_static(name), v.clone());
        }
    }
    out
}

fn split_target(target: &str) -> (&str, &str) {
    match target.split_once('?') {
        Some((p, q)) => (p, q),
        None => (target, ""),
    }
}

/// The same Prowlarr search with the narrator added: MAM's search also matches narrators, so its results are that narrator's releases.
pub fn narrator_search(target: &str, narrator: &str) -> String {
    let (path, query) = split_target(target);
    let mut pairs = parse_qs(query);
    let mut found = false;
    for (k, v) in pairs.iter_mut() {
        if k == "query" && !found {
            *v = format!("{v} {narrator}").trim().to_string();
            found = true;
        }
    }
    if !found {
        pairs.push(("query".to_string(), narrator.trim().to_string()));
    }
    let mut ser = form_urlencoded::Serializer::new(String::new());
    for (k, v) in &pairs {
        ser.append_pair(k, v);
    }
    format!("{path}?{}", ser.finish())
}

async fn narrated_guids(app: &App, target: &str, headers: &HeaderMap, narrators: &[String]) -> HashSet<String> {
    let mut found = HashSet::new();
    for n in narrators.iter().take(2) {
        if let Ok((200, body, _)) = prowlarr(&app.cfg, &app.http, Method::GET, &narrator_search(target, n), headers.clone(), None).await {
            if let Ok(Value::Array(results)) = serde_json::from_slice::<Value>(&body) {
                found.extend(results.iter().filter_map(|r| str_of(r.get("guid"))).map(String::from));
            }
        }
    }
    found
}

pub fn with_wedge(indexer: &Value, on: bool) -> Value {
    let mut out = indexer.clone();
    if let Some(fields) = out.get_mut("fields").and_then(Value::as_array_mut) {
        for f in fields.iter_mut() {
            if str_of(f.get("name")) == Some("useFreeleechWedge") {
                if let Some(o) = f.as_object_mut() {
                    o.insert("value".into(), Value::Bool(on));
                }
            }
        }
    }
    out
}

/// A wedge grab failed (e.g. no wedges left): retry once as a normal download, then switch the wedge back on.
async fn grab_without_wedge(app: &App, headers: &HeaderMap, data: Option<Bytes>) -> Option<(u16, Bytes, String)> {
    let mut key = HeaderMap::new();
    key.insert("x-api-key", headers.get("x-api-key").cloned().unwrap_or_else(|| HeaderValue::from_static("")));
    key.insert(header::CONTENT_TYPE, HeaderValue::from_static("application/json"));
    let (status, body, _) = prowlarr(&app.cfg, &app.http, Method::GET, "/api/v1/indexer", key.clone(), None).await.ok()?;
    if status != 200 {
        return None;
    }
    let indexers: Vec<Value> = serde_json::from_slice::<Value>(&body).ok()?.as_array().cloned()?;
    let mam = indexers.into_iter().find(|i| str_of(i.get("implementation")) == Some("MyAnonamouse"))?;
    let wedge_on = mam.get("fields").and_then(Value::as_array).is_some_and(|fs| fs.iter().any(|f| str_of(f.get("name")) == Some("useFreeleechWedge") && truthy(f.get("value"))));
    if !wedge_on {
        return None;
    }
    let id = mam.get("id").map(|v| v.to_string()).unwrap_or_default();
    let put = format!("/api/v1/indexer/{id}?forceSave=true");
    let _ = prowlarr(&app.cfg, &app.http, Method::PUT, &put, key.clone(), Some(Bytes::from(serde_json::to_vec(&with_wedge(&mam, false)).ok()?))).await;
    let result = prowlarr(&app.cfg, &app.http, Method::POST, "/api/v1/search", headers.clone(), data).await;
    let _ = prowlarr(&app.cfg, &app.http, Method::PUT, &put, key, Some(Bytes::from(serde_json::to_vec(&mam).ok()?))).await;
    let result = result.ok()?;
    log::warn!("grab with wedge failed, retried without: HTTP {}", result.0);
    Some(result)
}

/// The .torrent ABR wants for its hash: the abr torrent qBittorrent got in the last 3 minutes, never a new MAM download.
async fn torrent_file(app: &App) -> Result<(u16, Bytes, String)> {
    let t0 = now();
    let fresh: Vec<Value> = app.qbit.category().await?.into_iter().filter(|t| t0 - t.get("added_on").and_then(Value::as_f64).unwrap_or(0.0) < 180.0).collect();
    let Some(newest) = fresh.iter().max_by(|a, b| a.get("added_on").and_then(Value::as_f64).unwrap_or(0.0).total_cmp(&b.get("added_on").and_then(Value::as_f64).unwrap_or(0.0))) else {
        return Ok((404, Bytes::from_static(b"not found"), "text/plain".to_string()));
    };
    let hash = str_of(newest.get("hash")).unwrap_or("").to_string();
    Ok((200, app.qbit.export(&hash).await?, "application/x-bittorrent".to_string()))
}

/// Pass-through to Prowlarr; search results get the release policy (ranking.rs).
async fn forward(app: &App, method: Method, path_and_query: &str, headers: &HeaderMap, data: Option<Bytes>) -> Response {
    let target = &path_and_query["/prowlarr".len()..];
    let (path, query) = split_target(target);
    let pass = pass_headers(headers);
    let result = if method == Method::GET && path == "/torrent" {
        torrent_file(app).await
    } else {
        match prowlarr(&app.cfg, &app.http, method.clone(), target, pass.clone(), data.clone()).await {
            Ok((status, body, ctype)) if method == Method::POST && path == "/api/v1/search" && status >= 400 => {
                Ok(grab_without_wedge(app, &pass, data).await.unwrap_or((status, body, ctype)))
            }
            other => other,
        }
    };
    let (mut status, mut body, ctype) = match result {
        Ok(r) => r,
        Err(e) => {
            log::error!("prowlarr {target}: {e}");
            return respond(502, "text/plain", "Prowlarr not reachable", &[]);
        }
    };
    if method == Method::GET && path == "/api/v1/search" && status == 200 {
        let query_text = first_query(query, "query").unwrap_or_default();
        let prefs = app.prefs(&query_text).await;
        let results: Vec<Value> = serde_json::from_slice::<Value>(&body).ok().and_then(|v| v.as_array().cloned()).unwrap_or_default();
        let narrated = if !results.is_empty() && !prefs.narrators.is_empty() { narrated_guids(app, target, &pass, &prefs.narrators).await } else { HashSet::new() };
        let ranked = for_abr(results.clone(), &prefs, Some(&app.cfg.proxy_base), &narrated);
        log::info!(
            "search {query_text:?}: {} -> {} results ({}, unabridged={}, authors={:?}, narrator releases={})",
            results.len(),
            ranked.len(),
            prefs.language,
            prefs.unabridged,
            prefs.authors,
            narrated.len()
        );
        if ranked.is_empty() {
            let wanted: HashSet<String> = prefs.authors.iter().map(|a| norm_name(a)).collect();
            let by_author = results.iter().any(|r| wanted.is_empty() || release_authors(str_of(r.get("title"))).iter().any(|a| wanted.contains(a)));
            let reason = if by_author { "no release in the requested language with a seeder".to_string() } else { format!("no release by {}", prefs.authors.join(", ")) };
            log::warn!("search {query_text:?}: {reason}, no automatic grab (the request stays open for a manual pick)");
        }
        body = Bytes::from(serde_json::to_vec(&ranked).unwrap_or_default());
        status = 200;
    }
    respond(status, &ctype, body, &[])
}

static SEARCH: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^/api/libraries/[^/]+/search$").unwrap());

/// ABR's Audiobookshelf base URL. Its "already in library" search covers one library; ABS has one per language,
/// so a search is asked in every book library. Everything else passes through with ABR's own (read-only) key.
async fn abs_forward(app: &App, path_and_query: &str, headers: &HeaderMap) -> Response {
    let target = &path_and_query["/abs".len()..];
    let (path, query) = split_target(target);
    let auth = crate::clients::headers(&[("Authorization", &authorization(headers))]);
    let result: Result<(u16, Bytes)> = async {
        if SEARCH.is_match(path) {
            let libs = crate::clients::fetch_json(&app.http, Method::GET, &format!("{}/api/libraries", app.cfg.abs_url), auth.clone(), None, crate::clients::DEFAULT_TIMEOUT).await?;
            let libs = libs.get("libraries").and_then(Value::as_array).cloned().ok_or("no libraries")?;
            let mut found = vec![];
            for id in book_library_ids(&libs) {
                let v = crate::clients::fetch_json(&app.http, Method::GET, &format!("{}/api/libraries/{id}/search?{query}", app.cfg.abs_url), auth.clone(), None, crate::clients::DEFAULT_TIMEOUT).await?;
                found.push(if v.is_null() { json!({}) } else { v });
            }
            Ok((200, Bytes::from(serde_json::to_vec(&merge_searches(&found))?)))
        } else {
            let (status, _, body) = crate::clients::fetch(&app.http, Method::GET, &format!("{}{target}", app.cfg.abs_url), auth.clone(), None, crate::clients::DEFAULT_TIMEOUT).await?;
            if !status.is_success() {
                return Err(Box::new(HttpError { status: status.as_u16() }) as crate::util::Error);
            }
            Ok((status.as_u16(), body))
        }
    }
    .await;
    let (status, body) = match result {
        Ok(r) => r,
        Err(e) => match http_status(&e) {
            Some(code) => (code, Bytes::from_static(b"{}")),
            None => {
                log::warn!("abs: {e}");
                (502, Bytes::from_static(b"{}"))
            }
        },
    };
    respond(status, "application/json", body, &[])
}

fn status_text(downloaded: bool, job_state: Option<&str>) -> &'static str {
    if matches!(job_state, Some("pending") | Some("unbound") | Some("merge-wait")) {
        return "downloading";
    }
    if matches!(job_state, Some("done") | Some("exists")) || downloaded {
        return "in library";
    }
    "open"
}

fn joined(v: Option<&Value>) -> String {
    v.and_then(Value::as_array).map(|a| a.iter().filter_map(Value::as_str).collect::<Vec<_>>().join(", ")).unwrap_or_default()
}

/// Everyone's requests for the read-only "All requests" page (owner 2026-10-27: with names), newest first.
pub fn all_requests(wishlist: &[Value], manual: &[Value], jobs: &Map<String, Value>, sizes: Option<&Map<String, Value>>) -> Vec<Value> {
    let mut state: std::collections::HashMap<String, String> = std::collections::HashMap::new();
    for j in jobs.values() {
        if let Some(a) = str_of(j.get("asin")).filter(|a| !a.is_empty()) {
            state.insert(a.to_string(), str_of(j.get("state")).unwrap_or("").to_string());
        }
    }
    let null = Value::Null;
    let mut rows = vec![];
    for w in wishlist {
        let b = w.get("book").unwrap_or(&null);
        let asin = str_of(b.get("asin"));
        for r in w.get("requests").and_then(Value::as_array).into_iter().flatten() {
            rows.push(json!({
                "title": b.get("title").cloned().unwrap_or(Value::Null),
                "author": joined(b.get("authors")),
                "cover": b.get("cover_image").cloned().unwrap_or(Value::Null),
                "asin": b.get("asin").cloned().unwrap_or(Value::Null),
                "size": sizes.and_then(|s| asin.and_then(|a| s.get(a))).cloned().unwrap_or(Value::Null),
                "requested_by": r.get("user_username").cloned().unwrap_or(Value::Null),
                "requested": r.get("updated_at").cloned().unwrap_or(Value::Null),
                "status": status_text(truthy(b.get("downloaded")), asin.and_then(|a| state.get(a)).map(String::as_str)),
            }));
        }
    }
    for m in manual {
        rows.push(json!({
            "title": m.get("title").cloned().unwrap_or(Value::Null),
            "author": joined(m.get("authors")),
            "cover": Value::Null, "asin": Value::Null, "size": Value::Null,
            "requested_by": m.get("user_username").cloned().unwrap_or(Value::Null),
            "requested": m.get("updated_at").cloned().unwrap_or(Value::Null),
            "status": status_text(truthy(m.get("downloaded")), None),
        }));
    }
    rows.sort_by(|a, b| str_of(b.get("requested")).unwrap_or("").cmp(str_of(a.get("requested")).unwrap_or("")));
    rows
}

/// Sizes for ABR's lists, limited to the books the viewer's ABS account may see (like the library page).
async fn book_sizes(app: &App, username: &str) -> Result<Map<String, Value>> {
    let (libs, items) = app.abs_books().await?;
    let users = app.abs_users().await?;
    let allowed = library::visible_ids(library::abs_user(&users, username), &libs, &items);
    let jobs = {
        let _guard = app.jobs_lock.lock().await;
        load(&app.cfg.state)?
    };
    let torrents = match app.qbit.category().await {
        Ok(t) => t,
        Err(e) => {
            log::warn!("sizes: qBittorrent {e}");
            vec![]
        }
    };
    Ok(library::sizes(&items, &jobs, &torrents, &allowed))
}

async fn all_requests_handler(app: &App, headers: &HeaderMap) -> Response {
    let result: Result<Vec<Value>> = async {
        let jobs = {
            let _guard = app.jobs_lock.lock().await;
            load(&app.cfg.state)?
        };
        let sizes = book_sizes(app, &username(headers)).await.ok();
        let wishlist = abr_json(&app.cfg, &app.http, "/api/requests", &app.abr_key).await?.as_array().cloned().unwrap_or_default();
        let manual = abr_json(&app.cfg, &app.http, "/api/requests/manual", &app.abr_key).await?.as_array().cloned().unwrap_or_default();
        Ok(all_requests(&wishlist, &manual, &jobs, sizes.as_ref()))
    }
    .await;
    match result {
        Ok(rows) => json_response(200, &Value::Array(rows)),
        Err(e) => {
            log::error!("all-requests: {e}");
            respond(502, "application/json", "[]", &[("Cache-Control", "no-store")])
        }
    }
}

/// Library page: what the viewer's own ABS account may see (libraries, explicit, tags), no paths, keys or descriptions.
async fn library_handler(app: &App, headers: &HeaderMap) -> Response {
    let result: Result<Value> = async {
        let users = app.abs_users().await?;
        let (libs, items) = app.abs_books().await?;
        Ok(library::listing(library::abs_user(&users, &username(headers)), &libs, &items))
    }
    .await;
    match result {
        Ok(v) => json_response(200, &v),
        Err(e) => {
            log::error!("library: {e}");
            json_response(502, &json!({"error": "Audiobookshelf not reachable"}))
        }
    }
}

async fn cover_handler(app: &App, path: &str, headers: &HeaderMap) -> Response {
    let Some(item) = library::cover_id(path) else { return status(404) };
    let result: Result<(String, Bytes)> = async {
        let users = app.abs_users().await?;
        let (libs, items) = app.abs_books().await?;
        if !library::visible_ids(library::abs_user(&users, &username(headers)), &libs, &items).contains(&item) {
            return Err("not visible".into());
        }
        app.abs.cover(&item).await
    }
    .await;
    match result {
        Ok((ctype, body)) => {
            let ctype = if ctype.starts_with("image/") { ctype } else { "application/octet-stream".to_string() };
            respond(200, &ctype, body, &[("Cache-Control", "private, max-age=86400")])
        }
        Err(_) => status(404),
    }
}

async fn sizes_handler(app: &App, headers: &HeaderMap) -> Response {
    match book_sizes(app, &username(headers)).await {
        Ok(sizes) => json_response(200, &Value::Object(sizes)),
        Err(e) => {
            log::error!("sizes: {e}");
            json_response(502, &json!({}))
        }
    }
}

/// nginx auth_request for ABR's request endpoints: 204 = allowed, 403 = limit reached.
async fn quota_handler(app: &App, headers: &HeaderMap) -> Response {
    let user = username(headers);
    let original = headers.get("x-original-method").and_then(|v| v.to_str().ok()).unwrap_or("POST");
    let mut ok = original != "POST";
    if !ok {
        ok = match snapshot_quota(app).await {
            Ok((wishlist, manual, ledger)) => quota_ok(&wishlist, &manual, &user, now(), &ledger, app.cfg.quota_books, app.cfg.quota_days),
            Err(e) => {
                log::error!("quota check for {user}: {e}");
                false
            }
        };
        if !ok {
            log::info!("quota: {user} refused ({} per {} days)", app.cfg.quota_books, app.cfg.quota_days);
        }
    }
    respond(if ok { 204 } else { 403 }, "", Body::empty(), &[])
}

/// Requests bar: the logged-in user's quota from the ledger (refreshed every minute), as JSON.
async fn my_quota_handler(app: &App, headers: &HeaderMap) -> Response {
    let q = {
        let _guard = app.quota_lock.lock().await;
        let ledger = pipeline::load_ledger(&app.cfg.quota_ledger).unwrap_or_default();
        my_quota(&ledger, &username(headers), now(), app.cfg.quota_books, app.cfg.quota_days)
    };
    match q {
        Some(v) => json_response(200, &v),
        None => json_response(400, &Value::Null),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn caller_table() {
        for p in ["/quota", "/all-requests", "/my-quota", "/library", "/library-cover/x", "/sizes"] {
            assert_eq!(wanted_peer(p, &Method::GET), Some(Peer::BooksProxy), "{p}");
        }
        assert_eq!(wanted_peer("/prowlarr/torrent", &Method::GET), Some(Peer::Abr));
        assert_eq!(wanted_peer("/health", &Method::GET), None);
        assert_eq!(wanted_peer("/prowlarr/api/v1/search", &Method::GET), None);
        for p in ["/abr", "/prowlarr/api/v1/search", "/prowlarr/api/v1/indexer/1"] {
            assert_eq!(wanted_peer(p, &Method::POST), Some(Peer::Abr), "{p}");
        }
        assert_eq!(wanted_peer("/abs/api/libraries/x/scan", &Method::POST), None);
    }

    #[test]
    fn narrator_query() {
        let out = narrator_search("/api/v1/search?query=Sense+and+Sensibility&type=search&limit=100&categories=3030", "Karen Savage");
        let pairs = parse_qs(out.split_once('?').unwrap().1);
        assert_eq!(pairs, vec![("query".to_string(), "Sense and Sensibility Karen Savage".to_string()), ("type".into(), "search".into()), ("limit".into(), "100".into()), ("categories".into(), "3030".into())]);
    }

    #[test]
    fn wedge_toggle() {
        let idx = json!({"id": 1, "fields": [{"name": "useFreeleechWedge", "value": true}, {"name": "mamId", "value": "x"}]});
        let off = with_wedge(&idx, false);
        assert_eq!(off["fields"], json!([{"name": "useFreeleechWedge", "value": false}, {"name": "mamId", "value": "x"}]));
        assert_eq!(idx["fields"][0]["value"], true);
    }

    #[test]
    fn all_requests_rows() {
        let wish = |asin: &str, downloaded: bool, reqs: &[(&str, &str)]| {
            json!({"book": {"asin": asin, "title": format!("T{asin}"), "authors": ["Jane Doe", "X"], "cover_image": format!("https://img/{asin}.jpg"), "downloaded": downloaded},
                   "requests": reqs.iter().map(|(u, t)| json!({"user_username": u, "updated_at": t})).collect::<Vec<_>>()})
        };
        let wishlist = vec![wish("A1", false, &[("jane", "2026-10-20T10:00:00")]), wish("A2", true, &[("john", "2026-10-25T10:00:00"), ("jane", "2026-10-26T09:00:00")]),
                            wish("A3", true, &[("jane", "2026-10-24T10:00:00")])];
        let mut jobs = Map::new();
        jobs.insert("h2".into(), json!({"asin": "A2", "state": "pending"}));
        jobs.insert("h3".into(), json!({"asin": "A3", "state": "done"}));
        let rows = all_requests(&wishlist, &[], &jobs, None);
        let summary: Vec<(String, String, String)> = rows.iter().map(|r| (r["title"].as_str().unwrap().into(), r["requested_by"].as_str().unwrap().into(), r["status"].as_str().unwrap().into())).collect();
        assert_eq!(summary, [("TA2", "jane", "downloading"), ("TA2", "john", "downloading"), ("TA3", "jane", "in library"), ("TA1", "jane", "open")].map(|(a, b, c)| (a.into(), b.into(), c.into())));
        assert_eq!(rows[0]["author"], "Jane Doe, X");
        let manual = vec![json!({"title": "M", "authors": ["A"], "user_username": "jane", "updated_at": "2026-10-22T10:00:00", "downloaded": false})];
        let rows = all_requests(&[], &manual, &Map::new(), None);
        assert_eq!(rows[0], json!({"title": "M", "author": "A", "cover": null, "asin": null, "size": null, "requested_by": "jane", "requested": "2026-10-22T10:00:00", "status": "open"}));
        let mut sizes = Map::new();
        sizes.insert("A1".into(), json!(123));
        assert_eq!(all_requests(&wishlist[..1], &[], &Map::new(), Some(&sizes))[0]["size"], 123);
    }
}
