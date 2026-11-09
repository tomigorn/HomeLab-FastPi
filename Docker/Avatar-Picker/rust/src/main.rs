#![forbid(unsafe_code)]

mod authentik;
mod checks;
mod core;
mod queue;

use std::collections::{HashMap, HashSet};
use std::io::{self, Write};
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use bytes::Bytes;
use http_body_util::{BodyExt, Full, Limited};
use hyper::header::{self, HeaderValue};
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper::{Method, Request, Response, StatusCode};
use hyper_util::rt::{TokioIo, TokioTimer};
use serde_json::{json, Value};
use tokio::net::TcpListener;

use authentik::{AuthentikError, Client};

const THUMB_CACHE: &str = "private, max-age=31536000, immutable";
const PICKED_TTL: Duration = Duration::from_secs(30);
const SESSION_TTL: Duration = Duration::from_secs(60);
const SESSION_MAX: usize = 1000;
const MAX_PICK_BODY: u64 = 1024;
const HTML: &str = "text/html; charset=utf-8";
const TEXT: &str = "text/plain; charset=utf-8";
const JSON: &str = "application/json";

pub struct Gallery {
    pub entries: Vec<Value>,
    pub groups: Vec<Value>,
    pub ids: HashSet<String>,
    pub files: HashMap<String, PathBuf>,
    pub thumbs: HashMap<String, String>,
    pub thumb_files: HashMap<String, (String, PathBuf)>,
}

fn read_json(path: &Path) -> io::Result<Value> {
    serde_json::from_slice(&std::fs::read(path)?).map_err(|e| io::Error::other(format!("{}: {e}", path.display())))
}

/// Loads the gallery, hiding avatars (and then-empty groups) whose image file is missing.
pub fn load_gallery(app: &Path) -> io::Result<Gallery> {
    let mut entries: Vec<Value> = Vec::new();
    let mut files = HashMap::new();
    for g in read_json(&app.join("gallery.json"))?.as_array().cloned().unwrap_or_default() {
        let Some(id) = g.get("id").and_then(Value::as_str).map(str::to_string) else { continue };
        let pack = if g.get("pack").and_then(Value::as_str) == Some("local") { "img-local" } else { "img" };
        let path = app.join(pack).join(format!("{id}.png"));
        if path.is_file() {
            if files.insert(id.clone(), path).is_some() {
                if let Some(pos) = entries.iter().position(|e| e.get("id").and_then(Value::as_str) == Some(id.as_str())) {
                    entries[pos] = g;
                    continue;
                }
            }
            entries.push(g);
        }
    }
    let shown: HashSet<Option<String>> = entries.iter().map(|g| g.get("group").and_then(Value::as_str).map(str::to_string)).collect();
    let groups = read_json(&app.join("groups.json"))?
        .as_array()
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter(|r| shown.contains(&r.get("id").and_then(Value::as_str).map(str::to_string)))
        .collect();
    let ids: HashSet<String> = files.keys().cloned().collect();
    let manifest = app.join("thumbs").join("thumbs.json");
    let mut thumbs = HashMap::new();
    if manifest.is_file() {
        if let Some(m) = read_json(&manifest)?.as_object() {
            for (aid, h) in m {
                if let (true, Some(h)) = (ids.contains(aid), h.as_str()) {
                    thumbs.insert(aid.clone(), h.to_string());
                }
            }
        }
    }
    let mut thumb_files = HashMap::new();
    for (aid, h) in &thumbs {
        for w in [160, 320] {
            let name = format!("{aid}.{h}.{w}.webp");
            let p = app.join("thumbs").join(&name);
            if p.is_file() {
                thumb_files.insert(name, (aid.clone(), p));
            }
        }
    }
    Ok(Gallery { entries, groups, ids, files, thumbs, thumb_files })
}

struct Picked {
    ids: Option<HashSet<String>>,
    at: Option<Instant>,
}

struct App {
    gallery: Gallery,
    index: Bytes,
    index_gz: Bytes,
    icons: HashMap<&'static str, (Bytes, &'static str)>,
    version: String,
    client: Client,
    base: String,
    secret: String,
    queue: Option<PathBuf>,
    pick_lock: tokio::sync::Mutex<()>,
    picked: tokio::sync::Mutex<Picked>,
    sessions: Mutex<HashMap<Vec<u8>, Instant>>,
}

fn gzip(data: &[u8], level: u32) -> Bytes {
    let mut e = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::new(level));
    let _ = e.write_all(data);
    Bytes::from(e.finish().unwrap_or_default())
}

fn now_ts() -> String {
    core::utc_timestamp(SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0))
}

struct Ctx {
    head: bool,
    accepts_gzip: bool,
}

impl App {
    fn send(&self, ctx: &Ctx, code: StatusCode, body: Bytes, ctype: &'static str, cache: Option<&str>) -> Response<Full<Bytes>> {
        let gzip_type = ctype == HTML || ctype == JSON;
        let zipped = gzip_type && body.len() > 1024 && ctx.accepts_gzip;
        let body = match (zipped, body == self.index) {
            (false, _) => body,
            (true, true) => self.index_gz.clone(),
            (true, false) => gzip(&body, 6),
        };
        let mut r = Response::builder()
            .status(code)
            .header(header::CONTENT_TYPE, ctype)
            .header(header::CONTENT_LENGTH, body.len())
            .header("X-Content-Type-Options", "nosniff")
            .header(header::CACHE_CONTROL, cache.unwrap_or("no-store"));
        if gzip_type {
            r = r.header(header::VARY, "Accept-Encoding");
        }
        if zipped {
            r = r.header(header::CONTENT_ENCODING, "gzip");
        }
        r.body(Full::new(if ctx.head { Bytes::new() } else { body })).unwrap_or_default()
    }

    fn text(&self, ctx: &Ctx, code: StatusCode, msg: &'static str) -> Response<Full<Bytes>> {
        self.send(ctx, code, Bytes::from_static(msg.as_bytes()), TEXT, None)
    }

    fn json(&self, ctx: &Ctx, code: StatusCode, v: Value) -> Response<Full<Bytes>> {
        self.send(ctx, code, Bytes::from(v.to_string()), JSON, None)
    }

    fn secret_ok(&self, req: &Request<hyper::body::Incoming>) -> bool {
        let got = req.headers().get("X-Picker-Secret").map(HeaderValue::as_bytes).unwrap_or(b"");
        core::constant_time_eq(got, self.secret.as_bytes())
    }

    fn caller(req: &Request<hyper::body::Incoming>) -> Option<String> {
        let raw = req.headers().get("X-authentik-username")?.as_bytes();
        let v = core::header_text(raw).trim().to_string();
        (!v.is_empty()).then_some(v)
    }

    async fn picked_ids(&self) -> HashSet<String> {
        let mut p = self.picked.lock().await;
        let stale = p.ids.is_none() || p.at.is_none_or(|t| t.elapsed() > PICKED_TTL);
        if stale {
            match self.client.list_users().await {
                Ok(users) => p.ids = Some(core::picked_ids(&users, &self.base)),
                Err(e) => {
                    eprintln!("picked set: {e}");
                    p.ids.get_or_insert_with(HashSet::new);
                }
            }
            p.at = Some(Instant::now());
        }
        p.ids.clone().unwrap_or_default()
    }

    async fn reset_picked(&self) {
        let mut p = self.picked.lock().await;
        p.ids = None;
        p.at = None;
    }

    /// Cached positive answers only, keyed by a hash so the cookie itself is never kept.
    async fn session_valid(&self, cookie: &str) -> Result<bool, AuthentikError> {
        if cookie.is_empty() {
            return Ok(false);
        }
        let key = ring::digest::digest(&ring::digest::SHA256, cookie.as_bytes()).as_ref().to_vec();
        let now = Instant::now();
        if self.sessions.lock().map(|s| s.get(&key).is_some_and(|t| *t > now)).unwrap_or(false) {
            return Ok(true);
        }
        if !self.client.session_valid(cookie).await? {
            return Ok(false);
        }
        if let Ok(mut s) = self.sessions.lock() {
            if s.len() >= SESSION_MAX {
                s.retain(|_, t| *t > now);
                if s.len() >= SESSION_MAX {
                    let drop: Vec<Vec<u8>> = s.keys().take(SESSION_MAX / 2).cloned().collect();
                    for k in drop {
                        s.remove(&k);
                    }
                }
            }
            s.insert(key, now + SESSION_TTL);
        }
        Ok(true)
    }

    async fn image(&self, ctx: &Ctx, req: &Request<hyper::body::Incoming>, aid: &str, file: Option<&Path>, ctype: &'static str, thumb: bool) -> Response<Full<Bytes>> {
        let read = |p: &Path| {
            let p = p.to_path_buf();
            async move { tokio::fs::read(p).await.map(Bytes::from) }
        };
        let lan = req.headers().get("X-Avatar-Access").map(HeaderValue::as_bytes) == Some(b"lan");
        if lan || self.secret_ok(req) {
            let Some(f) = file else { return self.text(ctx, StatusCode::NOT_FOUND, "not found") };
            let cache = if thumb { THUMB_CACHE } else if lan { "public, max-age=86400" } else { "private, max-age=86400" };
            return match read(f).await {
                Ok(b) => self.send(ctx, StatusCode::OK, b, ctype, Some(cache)),
                Err(_) => self.text(ctx, StatusCode::NOT_FOUND, "not found"),
            };
        }
        if let Some(f) = file {
            if self.picked_ids().await.contains(aid) {
                if let Ok(b) = read(f).await {
                    return self.send(ctx, StatusCode::OK, b, ctype, Some("public, max-age=300"));
                }
            }
        }
        let cookie = req.headers().get(header::COOKIE).map(|v| core::header_text(v.as_bytes())).unwrap_or_default();
        match self.session_valid(core::session_cookie(&cookie)).await {
            Err(e) => {
                eprintln!("session check: {e}");
                return self.text(ctx, StatusCode::SERVICE_UNAVAILABLE, "Authentik unreachable");
            }
            Ok(false) => return self.text(ctx, StatusCode::FORBIDDEN, "forbidden"),
            Ok(true) => {}
        }
        let Some(f) = file else { return self.text(ctx, StatusCode::NOT_FOUND, "not found") };
        match read(f).await {
            Ok(b) => self.send(ctx, StatusCode::OK, b, ctype, Some(if thumb { THUMB_CACHE } else { "private, max-age=300" })),
            Err(_) => self.text(ctx, StatusCode::NOT_FOUND, "not found"),
        }
    }

    /// healthz, tab icons, images, thumbnails
    async fn public(&self, ctx: &Ctx, req: &Request<hyper::body::Incoming>, path: &str) -> Option<Response<Full<Bytes>>> {
        if path == "/healthz" {
            return Some(self.text(ctx, StatusCode::OK, "ok"));
        }
        if let Some((body, ctype)) = self.icons.get(path) {
            return Some(self.send(ctx, StatusCode::OK, body.clone(), ctype, Some("public, max-age=86400")));
        }
        if let Some(aid) = path.strip_prefix("/img/").and_then(|p| p.strip_suffix(".png")) {
            let file = self.gallery.files.get(aid).map(PathBuf::as_path);
            return Some(self.image(ctx, req, aid, file, "image/png", false).await);
        }
        if let Some(name) = path.strip_prefix("/thumb/") {
            let found = if core::thumb_name_ok(name) { self.gallery.thumb_files.get(name) } else { None };
            let aid = found.map(|(a, _)| a.as_str()).unwrap_or_else(|| name.split('.').next().unwrap_or(""));
            return Some(self.image(ctx, req, aid, found.map(|(_, p)| p.as_path()), "image/webp", true).await);
        }
        None
    }

    async fn pick(&self, ctx: &Ctx, req: Request<hyper::body::Incoming>) -> Response<Full<Bytes>> {
        if !self.secret_ok(&req) {
            return self.text(ctx, StatusCode::FORBIDDEN, "forbidden");
        }
        let Some(caller) = Self::caller(&req) else {
            return self.json(ctx, StatusCode::UNAUTHORIZED, json!({"error": "login required"}));
        };
        let n = match req.headers().get(header::CONTENT_LENGTH) {
            None => 0,
            Some(v) => v.to_str().ok().and_then(|s| s.trim().parse::<u64>().ok()).unwrap_or(u64::MAX),
        };
        if n > MAX_PICK_BODY {
            return self.json(ctx, StatusCode::BAD_REQUEST, json!({"error": "bad request"}));
        }
        let body = if n == 0 {
            Bytes::new()
        } else {
            match Limited::new(req.into_body(), n as usize).collect().await {
                Ok(b) => b.to_bytes(),
                Err(_) => return self.json(ctx, StatusCode::BAD_REQUEST, json!({"error": "bad request"})),
            }
        };
        let parsed: Option<Value> = if body.is_empty() { Some(json!({})) } else { serde_json::from_slice(&body).ok() };
        let aid = parsed.as_ref().and_then(Value::as_object).and_then(|o| o.get("id")).and_then(Value::as_str).map(str::to_string);
        let Some(aid) = aid.filter(|a| self.gallery.ids.contains(a)) else {
            return self.json(ctx, StatusCode::BAD_REQUEST, json!({"error": "unknown avatar"}));
        };
        let _guard = self.pick_lock.lock().await;
        let unreachable = |e: AuthentikError| {
            eprintln!("authentik: {e}");
            self.json(ctx, StatusCode::SERVICE_UNAVAILABLE, json!({"error": "Authentik unreachable"}))
        };
        let users = match self.client.list_users().await {
            Ok(u) => u,
            Err(e) => return unreachable(e),
        };
        let pk = match core::check_pick(&users, &self.base, &caller, &aid) {
            Ok(pk) => pk,
            Err(core::PickError::Taken) => return self.json(ctx, StatusCode::CONFLICT, json!({"error": "just taken - pick another"})),
            Err(core::PickError::UnknownUser) => return self.json(ctx, StatusCode::FORBIDDEN, json!({"error": "unknown user"})),
        };
        let current = match self.client.get_user(pk).await {
            Ok(u) => u.get("attributes").cloned(),
            Err(e) => return unreachable(e),
        };
        if let Err(e) = self.client.set_attributes(pk, core::merged_attributes(current.as_ref(), &self.base, &aid)).await {
            return unreachable(e);
        }
        self.reset_picked().await;
        if let Some(q) = &self.queue {
            if let Err(e) = queue::record(q, &caller, &aid, &now_ts()) {
                eprintln!("queue: {e}");
            }
        }
        println!("pick {caller} -> {aid}");
        self.json(ctx, StatusCode::OK, json!({"ok": true, "url": core::avatar_url(&self.base, &aid)}))
    }

    async fn handle(self: Arc<Self>, req: Request<hyper::body::Incoming>) -> Result<Response<Full<Bytes>>, io::Error> {
        let path = req.uri().path().to_string();
        let ctx = Ctx {
            head: req.method() == Method::HEAD,
            accepts_gzip: req.headers().get(header::ACCEPT_ENCODING).is_some_and(|v| v.as_bytes().windows(4).any(|w| w == b"gzip")),
        };
        if req.method() == Method::POST {
            if path != "/api/pick" {
                return Ok(self.text(&ctx, StatusCode::NOT_FOUND, "not found"));
            }
            return Ok(self.pick(&ctx, req).await);
        }
        if req.method() != Method::GET && req.method() != Method::HEAD {
            return Ok(self.text(&ctx, StatusCode::NOT_IMPLEMENTED, "unsupported method"));
        }
        if let Some(r) = self.public(&ctx, &req, &path).await {
            return Ok(r);
        }
        if ctx.head {
            return Ok(self.text(&ctx, StatusCode::NOT_FOUND, "not found"));
        }
        let is_page = path == "/" || path == "/index.html";
        if (is_page || path.starts_with("/api/")) && !self.secret_ok(&req) {
            return Ok(self.text(&ctx, StatusCode::FORBIDDEN, "forbidden"));
        }
        let caller = Self::caller(&req);
        if is_page {
            return Ok(match caller {
                Some(_) => self.send(&ctx, StatusCode::OK, self.index.clone(), HTML, None),
                None => self.text(&ctx, StatusCode::UNAUTHORIZED, "login required"),
            });
        }
        if path == "/api/state" {
            let Some(caller) = caller else {
                return Ok(self.json(&ctx, StatusCode::UNAUTHORIZED, json!({"error": "login required"})));
            };
            let users = match self.client.list_users().await {
                Ok(u) => u,
                Err(e) => {
                    eprintln!("authentik: {e}");
                    return Ok(self.json(&ctx, StatusCode::SERVICE_UNAVAILABLE, json!({"error": "Authentik unreachable"})));
                }
            };
            let avatars = core::gallery_state(&self.gallery.entries, &users, &self.base, &caller, &self.gallery.thumbs);
            let body = json!({"user": caller, "version": self.version, "groups": self.gallery.groups, "avatars": avatars});
            return Ok(self.json(&ctx, StatusCode::OK, body));
        }
        Ok(self.text(&ctx, StatusCode::NOT_FOUND, "not found"))
    }
}

fn env(name: &str) -> String {
    std::env::var(name).unwrap_or_else(|_| {
        eprintln!("{name} is not set");
        std::process::exit(2)
    })
}

fn read_secret(var: &str) -> String {
    match std::fs::read_to_string(env(var)) {
        Ok(s) => s.trim().to_string(),
        Err(e) => {
            eprintln!("{var}: {e}");
            std::process::exit(2)
        }
    }
}

pub fn app_dir() -> PathBuf {
    PathBuf::from(std::env::var("APP_DIR").unwrap_or_else(|_| "/app".into()))
}

pub fn listen_addr() -> String {
    std::env::var("LISTEN").unwrap_or_else(|_| "0.0.0.0:8080".into())
}

pub fn client_from_env() -> Client {
    Client::new(&env("AUTHENTIK_URL"), &read_secret("AUTHENTIK_TOKEN_FILE"))
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if !args.is_empty() {
        std::process::exit(checks::run(&args).await);
    }
    let dir = app_dir();
    let gallery = load_gallery(&dir).unwrap_or_else(|e| {
        eprintln!("gallery: {e}");
        std::process::exit(2)
    });
    let index = Bytes::from(std::fs::read(dir.join("static/index.html")).expect("static/index.html"));
    let mut icons = HashMap::new();
    for (path, file, ctype) in [
        ("/favicon.svg", "favicon.svg", "image/svg+xml"),
        ("/favicon-32.png", "favicon-32.png", "image/png"),
        ("/apple-touch-icon.png", "apple-touch-icon.png", "image/png"),
    ] {
        icons.insert(path, (Bytes::from(std::fs::read(dir.join("static").join(file)).expect("static icon")), ctype));
    }
    let version = std::fs::read_to_string(dir.join("VERSION")).map(|s| s.trim().to_string()).unwrap_or_else(|_| "dev".into());
    let secret = read_secret("PICKER_SECRET_FILE");
    if secret.is_empty() {
        eprintln!("PICKER_SECRET_FILE is empty");
        std::process::exit(2);
    }
    let queue = std::env::var("QUEUE_FILE").ok().filter(|q| !q.is_empty()).map(PathBuf::from);
    let app = Arc::new(App {
        index_gz: gzip(&index, 9),
        index,
        icons,
        version,
        client: client_from_env(),
        base: env("PUBLIC_BASE_URL").trim_end_matches('/').to_string(),
        secret,
        queue,
        gallery,
        pick_lock: tokio::sync::Mutex::new(()),
        picked: tokio::sync::Mutex::new(Picked { ids: None, at: None }),
        sessions: Mutex::new(HashMap::new()),
    });
    if let Some(q) = &app.queue {
        match app.client.list_users().await {
            Ok(users) => match queue::backfill(q, &users, &app.base, &now_ts()) {
                Ok(added) => println!("queue: backfilled {} pick(s)", added.len()),
                Err(e) => println!("queue: backfill skipped: {e}"),
            },
            Err(e) => println!("queue: backfill skipped: {e}"),
        }
    }
    let addr: SocketAddr = listen_addr().parse().expect("LISTEN must be host:port");
    let listener = TcpListener::bind(addr).await.expect("bind");
    println!("avatar-picker {} ({} avatars) listening on {addr}", app.version, app.gallery.ids.len());
    let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()).expect("signal");
    loop {
        tokio::select! {
            accepted = listener.accept() => {
                let Ok((stream, _)) = accepted else { continue };
                let app = app.clone();
                tokio::spawn(async move {
                    let conn = http1::Builder::new()
                        .timer(TokioTimer::new())
                        .header_read_timeout(Duration::from_secs(10))
                        .serve_connection(TokioIo::new(stream), service_fn(move |req| app.clone().handle(req)));
                    let _ = tokio::time::timeout(Duration::from_secs(120), conn).await;
                });
            }
            _ = term.recv() => break,
            _ = tokio::signal::ctrl_c() => break,
        }
    }
}
