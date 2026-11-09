//! Beefy-Waker: Wake-on-LAN gate + manual LAN wake page for beefy (Traefik forwardAuth on fastpi :9001),
//! Jellyfin sign-in-to-wake and cold-start holds, stream-token check, and wake recovery (plug power-cycle + alert).
#![forbid(unsafe_code)]

mod client;
mod history;
mod pyfmt;
mod recovery;
mod web;
mod wol;

use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use tokio::net::TcpListener;
use tokio::sync::Semaphore;

use recovery::{mono, tcp_up, Recovery, Timings};
use web::{html_escape, log, parse_qsl, py_int, qs_first, take_chars, Req, Resp};

const PROBE_TIMEOUT: Duration = Duration::from_secs(1);
const PUBLIC_WAKE_PREFIX: &str = "/beefy-wake";
const HISTORY_KEY: &str = "/key";
const HISTORY_KNOWN_HOSTS: &str = "/known_hosts";
const READY_CACHE_SECONDS: f64 = 5.0;
const HOLD_POLL_SECONDS: f64 = 1.0;
const STREAM_AUTH_CACHE_SECONDS: f64 = 60.0;
const STREAM_AUTH_CACHE_MAX: usize = 512;

const WAKE_PAGE: &str = include_str!("pages/wake.html");
const JF_PAGE: &str = include_str!("pages/jf.html");
const CARD_CSS: &str = include_str!("pages/card.css");

const RETRY_TITLE: &str = "Taking longer than it should";
const RETRY_TEXT: &str = "The server didn't start normally, so it is being restarted the hard way (power off and on). Trying once more\u{2026}";
const BROKEN_TITLE: &str = "The server can't be started right now";
const BROKEN_TEXT: &str = "Something seems to be broken, or maintenance work is going on. The admin has been notified. Please try again later.";

fn service_name(port: u16) -> String {
    match port {
        8096 => "Jellyfin",
        5055 => "Seerr",
        7878 => "Radarr",
        8989 => "Sonarr",
        9696 => "Prowlarr",
        6767 => "Bazarr",
        8081 => "SABnzbd",
        8080 => "qBittorrent",
        8090 => "Dependency-Track",
        8012 => "Tracker",
        8087 => "VPN status",
        _ => return format!("port {port}"),
    }
    .to_string()
}

struct App {
    mac_str: String,
    broadcast: String,
    probe_host: String,
    probe_port: u16,
    jellyfin_port: u16,
    trusted_proxy: String,
    ssh_user: String,
    history_since: i64,
    hold_seconds: f64,
    public_info_cache: String,
    page: String,
    page_auto: String,
    jf_page: String,
    recovery: Arc<Recovery>,
    ready_until: Mutex<f64>,
    hold_slots: Semaphore,
    public_info: Mutex<Option<Vec<u8>>>,
    stream_cache: Mutex<Vec<(String, f64)>>,
}

fn lock<T>(m: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

/// str.strip() on a latin-1 decoded header value
fn py_strip(s: &str) -> &str {
    s.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
}

fn card_page(title: &str, body: &str, refresh: Option<u32>) -> String {
    let meta = refresh.map(|r| format!("<meta http-equiv=\"refresh\" content=\"{r}\">")).unwrap_or_default();
    format!(
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n{meta}<title>{}</title>\n<style>{CARD_CSS}</style></head>\n<body><div class=\"card\">\n{body}\n</div></body></html>",
        html_escape(title, false)
    )
}

fn is_browser_navigation(r: &Req) -> bool {
    r.header_or("Accept").to_lowercase().contains("text/html")
}

/// Sec-Fetch-Dest other than document/empty = a browser fetching a page's own assets.
fn is_browser_subresource(r: &Req) -> bool {
    let dest = py_strip(r.header_or("Sec-Fetch-Dest")).to_lowercase();
    !dest.is_empty() && dest != "document" && dest != "empty"
}

fn is_browser(r: &Req) -> bool {
    is_browser_navigation(r) || is_browser_subresource(r)
}

fn is_mediabrowser_client(r: &Req) -> bool {
    py_strip(r.header_or("Authorization")).to_lowercase().starts_with("mediabrowser")
}

/// (path, query) of the original request from X-Forwarded-Uri.
fn forwarded_path_query(r: &Req) -> (String, String) {
    let raw = r.header("X-Forwarded-Uri").filter(|v| !v.is_empty()).unwrap_or("/");
    let raw = raw.split('#').next().unwrap_or("");
    match raw.split_once('?') {
        Some((p, q)) => (p.to_string(), q.to_string()),
        None => (raw.to_string(), String::new()),
    }
}

fn query_keys(query: &str) -> Vec<String> {
    match parse_qsl(query, true, Some(50)) {
        Err(_) => vec!["<too many>".to_string()],
        Ok(pairs) => {
            let mut keys: Vec<String> = pairs.into_iter().map(|(k, _)| k).collect();
            keys.sort();
            keys.dedup();
            keys.into_iter().take(20).map(|k| take_chars(&k, 40).to_string()).collect()
        }
    }
}

fn client_ip(r: &Req) -> String {
    for name in ["CF-Connecting-IP", "X-Real-Ip"] {
        let v = py_strip(r.header_or(name));
        if !v.is_empty() {
            return take_chars(v, 45).to_string();
        }
    }
    let xff = r.header_or("X-Forwarded-For");
    take_chars(py_strip(xff.split(',').next().unwrap_or("")), 45).to_string()
}

/// `Client="..."` from the first occurrence (regex `Client="([^"]*)"`).
fn client_name(s: &str) -> Option<&str> {
    let i = s.find("Client=\"")? + 8;
    let rest = &s[i..];
    rest.find('"').map(|j| &rest[..j])
}

/// Redacted fingerprint of a Jellyfin request: never a token or a query value.
fn observe_record(r: &Req, up: bool, decision: &str) -> Map<String, Value> {
    let (path, query) = forwarded_path_query(r);
    let mb = is_mediabrowser_client(r);
    let emby = r.header_or("X-Emby-Authorization");
    let client = client_name(if mb { r.header_or("Authorization") } else { emby }).map(|c| take_chars(c, 40).to_string()).unwrap_or_default();
    let s = |v: &str, n: usize| Value::String(take_chars(v, n).to_string());
    let mut m = Map::new();
    m.insert("up".into(), Value::Bool(up));
    m.insert("decision".into(), Value::String(decision.into()));
    m.insert("method".into(), Value::String(r.header_or("X-Forwarded-Method").to_string()));
    m.insert("path".into(), s(&path, 200));
    m.insert("query_keys".into(), Value::Array(query_keys(&query).into_iter().map(Value::String).collect()));
    m.insert("auth_mediabrowser".into(), Value::Bool(mb));
    m.insert("x_emby_authorization".into(), Value::Bool(!emby.is_empty()));
    m.insert("x_emby_token".into(), Value::Bool(!r.header_or("X-Emby-Token").is_empty()));
    m.insert("x_mediabrowser_token".into(), Value::Bool(!r.header_or("X-MediaBrowser-Token").is_empty()));
    m.insert("client".into(), Value::String(client));
    m.insert("ua".into(), s(r.header_or("User-Agent"), 160));
    m.insert("accept".into(), s(r.header_or("Accept"), 80));
    m.insert("sec_fetch_mode".into(), s(r.header_or("Sec-Fetch-Mode"), 20));
    m.insert("sec_fetch_dest".into(), s(r.header_or("Sec-Fetch-Dest"), 20));
    m.insert("ip".into(), Value::String(client_ip(r)));
    m
}

fn float_value(f: f64) -> Value {
    serde_json::Number::from_f64(f).map(Value::Number).unwrap_or(Value::Null)
}

fn log_observe(r: &Req, rec: Map<String, Value>) {
    log(&r.peer, &format!("observe {}", pyfmt::dumps_sorted(&Value::Object(rec))));
}

/// The Jellyfin token from any place Jellyfin reads one; None if absent or malformed.
fn stream_token(r: &Req) -> Option<String> {
    let mut found: Option<String> = None;
    for name in ["Authorization", "X-Emby-Authorization"] {
        if let Some(t) = token_param(r.header_or(name)) {
            found = Some(t.to_string());
            break;
        }
    }
    if found.is_none() {
        found = r
            .header("X-Emby-Token")
            .filter(|v| !v.is_empty())
            .or(r.header("X-MediaBrowser-Token").filter(|v| !v.is_empty()))
            .map(str::to_string);
    }
    if found.is_none() {
        let (_, query) = forwarded_path_query(r);
        let pairs = parse_qsl(&query, false, Some(50)).unwrap_or_default();
        let mut seen: Vec<&str> = Vec::new();
        for (k, v) in &pairs {
            if seen.contains(&k.as_str()) {
                continue;
            }
            seen.push(k);
            let lk = k.to_lowercase();
            if lk == "api_key" || lk == "apikey" {
                found = Some(v.clone());
                break;
            }
        }
    }
    let t = found?;
    let ok = (8..=256).contains(&t.len()) && t.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b'_' || b == b'-');
    ok.then_some(t)
}

/// regex `(?i)(?:^|[\s,])Token="([^"]*)"`
fn token_param(s: &str) -> Option<&str> {
    let lower = s.to_ascii_lowercase();
    let mut from = 0;
    while let Some(i) = lower[from..].find("token=\"").map(|i| i + from) {
        let ok_prefix = i == 0 || s[..i].chars().next_back().is_some_and(|c| c.is_whitespace() || c == ',');
        if ok_prefix {
            let rest = &s[i + 7..];
            return rest.find('"').map(|j| &rest[..j]);
        }
        from = i + 1;
    }
    None
}

/// CSRF guard: a cross-site page cannot add X-Wake without a CORS preflight, which the waker never answers.
fn wake_request_allowed(r: &Req) -> bool {
    if r.header("X-Wake") != Some("1") {
        return false;
    }
    let Some(origin) = r.header("Origin") else { return true };
    let host = r.header_or("Host").to_lowercase();
    !host.is_empty() && origin_netloc(origin).to_lowercase() == host
}

/// `urlparse(origin).netloc`
fn origin_netloc(origin: &str) -> &str {
    let mut u = origin;
    if let Some(i) = u.find(':') {
        let scheme = &u[..i];
        if i > 0 && scheme.as_bytes()[0].is_ascii_alphabetic() && scheme.bytes().all(|b| b.is_ascii_alphanumeric() || b"+-.".contains(&b)) {
            u = &u[i + 1..];
        }
    }
    match u.strip_prefix("//") {
        Some(rest) => &rest[..rest.find(['/', '?', '#']).unwrap_or(rest.len())],
        None => "",
    }
}

impl App {
    fn status_json(&self, up: bool) -> Resp {
        let st = self.recovery.status();
        let left = st.seconds_left.map(|l| l.to_string()).unwrap_or_else(|| "null".into());
        Resp::json(200, format!("{{\"up\": {up}, \"phase\": \"{}\", \"seconds_left\": {left}, \"reason\": \"{}\"}}", st.phase, st.reason))
    }

    fn waking_page(&self) -> String {
        let st = self.recovery.status();
        let (title, paras, spin): (&str, Vec<String>, bool) = match st.phase {
            "broken" => (BROKEN_TITLE, vec![BROKEN_TEXT.into()], false),
            "power_cycle" | "retrying" => {
                let mut p = vec![RETRY_TEXT.to_string()];
                if let Some(l) = st.seconds_left {
                    p.push(format!("About {} s to go.", l.max(0)));
                }
                (RETRY_TITLE, p, true)
            }
            _ => ("Waking up beefy...", vec!["A magic packet is on its way. This page refreshes automatically.".into(), "The server should be ready in under a minute.".into()], true),
        };
        let mut body = if spin { "<div class=\"spin\"></div>\n  ".to_string() } else { String::new() };
        body.push_str(&format!("<h1>{}</h1>", html_escape(title, false)));
        for t in paras {
            body.push_str(&format!("\n  <p>{}</p>", html_escape(&t, false)));
        }
        card_page(title, &body, Some(if title == BROKEN_TITLE { 30 } else { 5 }))
    }

    fn signin_page(&self) -> String {
        if self.recovery.status().phase == "broken" {
            let body = format!("<h1>{}</h1>\n  <p>{}</p>", html_escape(BROKEN_TITLE, false), html_escape(BROKEN_TEXT, false));
            return card_page(BROKEN_TITLE, &body, None);
        }
        let body = "<div class=\"moon\">&#128164;</div>\n  <h1>Jellyfin is asleep</h1>\n  <p>The media server sleeps to save power.</p>\n  <a class=\"btn\" href=\"/beefy-wake/\">Sign in to start it</a>\n  <p>It takes about a minute to start after you sign in.</p>";
        card_page("Jellyfin is asleep", body, None)
    }

    fn waking_resp(&self) -> Resp {
        Resp::html(503, self.waking_page()).retry_after(5)
    }

    fn is_signed_in(&self, r: &Req, flagged: bool) -> bool {
        flagged && r.peer == self.trusted_proxy && !py_strip(r.header_or("X-Authentik-Username")).is_empty()
    }

    fn wake(&self, port: u16, signed_in: bool, user: &str, service: &str) -> std::io::Result<()> {
        self.recovery.start(port, signed_in, user, service)
    }

    async fn is_up(&self, port: u16) -> bool {
        tcp_up(&self.probe_host, port).await
    }

    /// Jellyfin's /health says Healthy; a healthy answer is reused for 5 s, an unhealthy one never.
    async fn jellyfin_ready(&self, port: u16) -> bool {
        if mono() < *lock(&self.ready_until) {
            return true;
        }
        let ready = match client::request("GET", &self.probe_host, port, "/health", &[], None, 64, PROBE_TIMEOUT).await {
            Ok(r) => {
                let head = &r.body[..r.body.len().min(64)];
                r.status == 200 && head.trim_ascii() == b"Healthy"
            }
            Err(_) => false,
        };
        if ready {
            *lock(&self.ready_until) = mono() + READY_CACHE_SECONDS;
        }
        ready
    }

    /// Wait for Jellyfin until `started + limit`; (ready, seconds held). No free slot = answer at once.
    async fn hold_until_ready(&self, port: u16, limit: f64, started: f64) -> (bool, f64) {
        let Ok(_permit) = self.hold_slots.try_acquire() else { return (false, 0.0) };
        let t0 = mono();
        let deadline = started + limit;
        loop {
            if self.jellyfin_ready(port).await {
                return (true, mono() - t0);
            }
            let remaining = deadline - mono();
            if remaining <= PROBE_TIMEOUT.as_secs_f64() {
                return (false, mono() - t0);
            }
            tokio::time::sleep(Duration::from_secs_f64(HOLD_POLL_SECONDS.min(remaining - PROBE_TIMEOUT.as_secs_f64()))).await;
        }
    }

    async fn jellyfin_decision(&self, up: bool, r: &Req) -> &'static str {
        if up {
            "pass"
        } else if self.recovery.in_progress() || self.is_up(self.probe_port).await {
            "starting"
        } else if is_browser(r) {
            "signin"
        } else {
            "wake"
        }
    }

    fn store_public_info(&self, data: &[u8]) {
        {
            let mut cur = lock(&self.public_info);
            if cur.as_deref() == Some(data) {
                return;
            }
            *cur = Some(data.to_vec());
        }
        let tmp = format!("{}.tmp", self.public_info_cache);
        if std::fs::write(&tmp, data).is_ok() {
            let _ = std::fs::rename(&tmp, &self.public_info_cache);
        }
    }

    /// Relay Jellyfin's /System/Info/Public; only a 200 JSON object with an "Id" (<= 64 KiB) counts and is cached.
    async fn fetch_public_info(&self, timeout: Duration) -> Option<Vec<u8>> {
        let r = client::request("GET", &self.probe_host, self.jellyfin_port, "/System/Info/Public", &[], None, 65536, timeout).await.ok()?;
        if r.status != 200 || r.truncated {
            return None;
        }
        let v: Value = serde_json::from_slice(&r.body).ok()?;
        if !v.as_object()?.contains_key("Id") {
            return None;
        }
        self.store_public_info(&r.body);
        Some(r.body)
    }

    fn load_public_info(&self) {
        if let Ok(data) = std::fs::read(&self.public_info_cache) {
            if serde_json::from_slice::<Value>(&data).is_ok() {
                *lock(&self.public_info) = Some(data);
            }
        }
    }

    /// True/False = Jellyfin accepts/refuses the token; None = Jellyfin did not answer.
    async fn check_stream_token(&self, token: &str) -> Option<bool> {
        let key = format!("{:x}", Sha256::digest(token.as_bytes()));
        let now = mono();
        if lock(&self.stream_cache).iter().any(|(k, t)| *k == key && *t > now) {
            return Some(true);
        }
        let auth = format!("MediaBrowser Token=\"{token}\"");
        let r = client::request("GET", &self.probe_host, self.jellyfin_port, "/System/Info", &[("authorization", auth.as_str())], None, 1 << 16, Duration::from_secs(3)).await.ok()?;
        let ok = match r.status {
            200 => true,
            401 | 403 => false,
            s if (200..300).contains(&s) => false,
            _ => return None,
        };
        if ok {
            let mut c = lock(&self.stream_cache);
            if c.len() >= STREAM_AUTH_CACHE_MAX {
                let before = c.len();
                c.retain(|(_, t)| *t > now);
                if c.len() == before {
                    c.remove(0);
                }
            }
            c.retain(|(k, _)| *k != key);
            c.push((key, now + STREAM_AUTH_CACHE_SECONDS));
        }
        Some(ok)
    }

    async fn handle(self: Arc<Self>, r: Req) -> Resp {
        match r.route().as_str() {
            "/" => Resp::html(200, self.page.clone()),
            "/wol" => Resp::html(200, self.page_auto.clone()),
            "/status" => {
                let up = self.is_up(self.probe_port).await;
                self.status_json(up)
            }
            "/wake" => self.lan_wake(&r),
            "/history" => self.history(&r).await,
            "/gate" => self.gate(&r).await,
            "/jf" => Resp::html(200, self.jf_page.clone()),
            "/jf/status" => {
                let up = self.jellyfin_ready(self.jellyfin_port).await;
                self.status_json(up)
            }
            "/jf/wake" => self.jf_wake(&r),
            "/jf/public-info" => self.jf_public_info(&r).await,
            "/stream-auth" => self.stream_auth(&r).await,
            _ => Resp::not_found(),
        }
    }

    fn wake_guard(r: &Req) -> Option<Resp> {
        if r.method != "POST" {
            return Some(Resp::json(405, r#"{"error": "POST only"}"#));
        }
        if !wake_request_allowed(r) {
            return Some(Resp::json(403, r#"{"error": "needs X-Wake: 1 from this origin"}"#));
        }
        None
    }

    fn sent(ok: bool) -> Resp {
        Resp::json(200, if ok { r#"{"sent": true}"# } else { r#"{"sent": false}"# })
    }

    fn lan_wake(&self, r: &Req) -> Resp {
        if let Some(refused) = Self::wake_guard(r) {
            return refused;
        }
        match self.wake(self.probe_port, false, "", "") {
            Ok(()) => {
                log(&r.peer, &format!("manual wake -> sent WoL to {} via {}", self.mac_str, self.broadcast));
                Self::sent(true)
            }
            Err(e) => {
                log(&r.peer, &format!("WoL send failed: {e}"));
                Self::sent(false)
            }
        }
    }

    fn jf_wake(&self, r: &Req) -> Resp {
        if let Some(refused) = Self::wake_guard(r) {
            return refused;
        }
        let signed_in = self.is_signed_in(r, true);
        let user = if signed_in { take_chars(py_strip(r.header_or("X-Authentik-Username")), 64).to_string() } else { String::new() };
        match self.wake(self.jellyfin_port, signed_in, &user, "Jellyfin") {
            Ok(()) => {
                let who = if user.is_empty() { "?" } else { &user };
                log(&r.peer, &format!("jf wake by {who} -> sent WoL to {} via {}", self.mac_str, self.broadcast));
                Self::sent(true)
            }
            Err(e) => {
                log(&r.peer, &format!("WoL send failed: {e}"));
                Self::sent(false)
            }
        }
    }

    fn log_wake(&self, r: &Req, port: u16, res: std::io::Result<()>) {
        match res {
            Ok(()) => log(&r.peer, &format!("beefy down ({}:{port}) - sent WoL to {} via {}", self.probe_host, self.mac_str, self.broadcast)),
            Err(e) => log(&r.peer, &format!("WoL send failed: {e}")),
        }
    }

    async fn gate(&self, r: &Req) -> Resp {
        let started = mono();
        let q = r.query();
        let port = qs_first(&q, "port")
            .and_then(|p| py_int(&p))
            .filter(|p| (1..=65535).contains(p))
            .map(|p| p as u16)
            .unwrap_or(self.probe_port);
        if qs_first(&q, "policy").as_deref() == Some("jellyfin") {
            let up = self.jellyfin_ready(port).await;
            return self.gate_jellyfin(r, up, port, started).await;
        }
        if self.is_up(port).await {
            return Resp::text(200, "");
        }
        let signed_in = self.is_signed_in(r, qs_first(&q, "signed_in").as_deref() == Some("1"));
        let user = if signed_in { take_chars(py_strip(r.header_or("X-Authentik-Username")), 64).to_string() } else { String::new() };
        let res = self.wake(port, signed_in, &user, &service_name(port));
        self.log_wake(r, port, res);
        self.waking_resp()
    }

    /// Browsers asleep get the sign-in page (no wake); apps wake and are held until Jellyfin is healthy (bounded).
    async fn gate_jellyfin(&self, r: &Req, up: bool, port: u16, started: f64) -> Resp {
        let decision = self.jellyfin_decision(up, r).await;
        let mut outcome = decision;
        let mut held = 0.0;
        if decision == "wake" {
            let res = self.wake(port, false, "", &service_name(port));
            self.log_wake(r, port, res);
        }
        if decision == "wake" || (decision == "starting" && !is_browser(r)) {
            let (ready, h) = self.hold_until_ready(port, self.hold_seconds, started).await;
            held = h;
            if ready {
                outcome = "pass";
            }
        }
        let (fwd_path, _) = forwarded_path_query(r);
        if !up || format!("/{}", fwd_path.trim_start_matches('/')).to_lowercase() == "/system/info/public" {
            let mut rec = observe_record(r, up, decision);
            rec.insert("held".into(), float_value(pyfmt::round1(held)));
            log_observe(r, rec);
        }
        match outcome {
            "pass" => Resp::text(200, ""),
            "signin" => Resp::html(503, self.signin_page()),
            _ => self.waking_resp(),
        }
    }

    /// GET /System/Info/Public on the Jellyfin host: relay + cache while healthy; while down apps are held, then get the cached identity.
    async fn jf_public_info(&self, r: &Req) -> Resp {
        let started = mono();
        let up = self.jellyfin_ready(self.jellyfin_port).await;
        let decision = self.jellyfin_decision(up, r).await;
        let mut held = 0.0;
        let mut cached = false;
        let mut body: Option<Vec<u8>> = None;
        let browser = is_browser(r);
        let budget = |hold: f64| Duration::from_secs_f64((started + hold - mono()).clamp(0.5, 3.0));
        let cache = || if is_mediabrowser_client(r) { lock(&self.public_info).clone() } else { None };
        if decision == "pass" {
            body = self.fetch_public_info(budget(self.hold_seconds)).await;
            if body.is_none() {
                body = cache();
                cached = body.is_some();
            }
        } else if decision != "signin" {
            if decision == "wake" {
                let res = self.wake(self.jellyfin_port, false, "", "Jellyfin");
                self.log_wake(r, self.jellyfin_port, res);
            }
            let mut ready = false;
            if decision == "wake" || !browser {
                let (rd, h) = self.hold_until_ready(self.jellyfin_port, self.hold_seconds, started).await;
                ready = rd;
                held = h;
            }
            if ready {
                body = self.fetch_public_info(budget(self.hold_seconds)).await;
            }
            if body.is_none() {
                body = cache();
                cached = body.is_some();
            }
        }
        let mut rec = observe_record(r, up, decision);
        rec.insert("path".into(), Value::String("/System/Info/Public".into()));
        rec.insert("method".into(), Value::String(r.method.clone()));
        rec.insert("query_keys".into(), Value::Array(query_keys(&r.query()).into_iter().map(Value::String).collect()));
        rec.insert("held".into(), float_value(pyfmt::round1(held)));
        rec.insert("cached".into(), Value::Bool(cached));
        log_observe(r, rec);
        if decision == "signin" {
            Resp::html(503, self.signin_page())
        } else if let Some(b) = body {
            Resp::json(200, b).cors()
        } else {
            self.waking_resp()
        }
    }

    async fn stream_auth(&self, r: &Req) -> Resp {
        if r.header_or("X-Forwarded-Method").to_uppercase() == "OPTIONS" {
            return Resp::text(200, "");
        }
        let ok = match stream_token(r) {
            Some(t) => self.check_stream_token(&t).await,
            None => Some(false),
        };
        match ok {
            None => Resp::text(503, "jellyfin unavailable").retry_after(5),
            Some(true) => Resp::text(200, ""),
            Some(false) => Resp::text(401, "unauthorized"),
        }
    }

    async fn history(&self, r: &Req) -> Resp {
        if !(Path::new(HISTORY_KEY).exists() && Path::new(HISTORY_KNOWN_HOSTS).exists()) {
            return Resp::json(503, r#"{"error": "history key not installed"}"#);
        }
        let unavailable = |e: &str| {
            log(&r.peer, &format!("history error: {e}"));
            Resp::json(503, r#"{"error": "history unavailable"}"#)
        };
        let run = match history::fetch(&self.probe_host, &self.ssh_user, HISTORY_KEY, HISTORY_KNOWN_HOSTS).await {
            Ok(run) => run,
            Err(e) => return unavailable(&e),
        };
        let out = run.stdout.trim();
        if run.code != 0 || !out.starts_with('[') {
            log(&r.peer, &format!("history fetch failed rc={}: {}", run.code, take_chars(run.error.trim(), 120)));
            return Resp::json(503, r#"{"error": "beefy unreachable"}"#);
        }
        let boots: Value = match serde_json::from_str(out) {
            Ok(v) => v,
            Err(e) => return unavailable(&e.to_string()),
        };
        let Value::Array(mut boots) = boots else { return unavailable("unexpected history payload") };
        if self.history_since != 0 {
            let since = self.history_since as f64;
            let mut kept = Vec::new();
            for b in boots {
                let Some(o) = b.as_object() else { continue };
                let fe = match o.get("first_entry") {
                    None => 0.0,
                    Some(Value::Number(n)) => n.as_f64().unwrap_or(0.0),
                    Some(Value::Bool(x)) => *x as i64 as f64,
                    Some(_) => return unavailable("'>=' not supported for first_entry"),
                };
                if fe >= since {
                    kept.push(b);
                }
            }
            boots = kept;
        }
        Resp::json(200, pyfmt::dumps(&Value::Array(boots)))
    }
}

fn env_or(k: &str, d: &str) -> String {
    std::env::var(k).unwrap_or_else(|_| d.to_string())
}

fn fail(msg: &str) -> ! {
    eprintln!("{msg}");
    std::process::exit(1);
}

fn env_int(k: &str, d: &str) -> i64 {
    let v = env_or(k, d);
    py_int(&v).unwrap_or_else(|| fail(&format!("invalid literal for int() with base 10: '{v}' ({k})")))
}

fn env_port(k: &str, d: &str) -> u16 {
    u16::try_from(env_int(k, d)).unwrap_or_else(|_| fail(&format!("{k} out of range")))
}

/// 0..25 (Traefik's forwardAuth limit is a fixed 30 s); 18 on bad input.
fn clamp_hold_seconds(v: &str) -> f64 {
    match v.trim().replace('_', "").parse::<f64>() {
        Ok(f) if !f.is_nan() => f.clamp(0.0, 25.0),
        _ => 18.0,
    }
}

/// At least 1; 16 on bad input.
fn clamp_hold_slots(v: &str) -> usize {
    py_int(v).map(|n| n.max(1) as usize).unwrap_or(16)
}

fn read_version() -> String {
    match std::fs::read_to_string(env_or("WAKER_VERSION_FILE", "/app/VERSION")) {
        Ok(v) if !v.trim().is_empty() => v.trim().to_string(),
        _ => "dev".to_string(),
    }
}

fn main() {
    let port = env_port("WAKER_LISTEN_PORT", "9001");
    let bind = env_or("WAKER_BIND", "0.0.0.0");
    if std::env::args().nth(1).as_deref() == Some("--health") {
        std::process::exit(web::health_check(&bind, port));
    }
    let mac_str = env_or("BEEFY_MAC", "");
    let broadcast = env_or("BEEFY_BROADCAST", "255.255.255.255");
    let probe_host = env_or("BEEFY_PROBE_HOST", "");
    let probe_port = env_port("BEEFY_PROBE_PORT", "22");
    let countdown = env_int("WAKE_COUNTDOWN", "60");
    let ssh_user = env_or("BEEFY_SSH_USER", "buntu");
    let history_since = env_int("BEEFY_HISTORY_SINCE", "0");
    let retry_interval = env_int("WAKE_RETRY_INTERVAL", "20");
    let retry_window = env_int("WAKE_RETRY_WINDOW", "300");
    let trusted_proxy = env_or("TRUSTED_PROXY", "172.24.255.3");
    let plug = env_or("BEEFY_PLUG", "http://192.168.1.152");
    let alert_url = env_or("ALERTMANAGER_URL", "http://127.0.0.1:9093");
    let metrics = env_or("WAKE_METRICS", "/textfile/beefy_wake.prom");
    let t1 = env_int("WAKE_T1", "120");
    let t2 = env_int("WAKE_T2", "150");
    let jellyfin_port = env_port("JELLYFIN_PORT", "8096");
    let hold_seconds = clamp_hold_seconds(&env_or("HOLD_SECONDS", "18"));
    let hold_slots = clamp_hold_slots(&env_or("HOLD_SLOTS", "16"));
    let public_info_cache = env_or("PUBLIC_INFO_CACHE", "/tmp/public-info.json");
    let state_file = env_or("WAKE_STATE_FILE", "/tmp/power-cycle.state");

    let missing: Vec<&str> = [("BEEFY_MAC", &mac_str), ("BEEFY_PROBE_HOST", &probe_host)].iter().filter(|(_, v)| v.is_empty()).map(|(k, _)| *k).collect();
    if !missing.is_empty() {
        fail(&format!("missing required env: {}", missing.join(", ")));
    }
    let mac = wol::parse_mac(&mac_str).unwrap_or_else(|| fail(&format!("invalid MAC: '{mac_str}'")));
    let version = read_version();
    let page = |auto: &str| WAKE_PAGE.replace("__COUNTDOWN__", &countdown.to_string()).replace("__AUTOWAKE__", auto).replace("__VERSION__", &version);
    let recovery = Arc::new(Recovery::new(
        Timings::new(t1 as f64, t2 as f64, retry_interval as f64, retry_window as f64),
        probe_host.clone(),
        probe_port,
        mac,
        broadcast.clone(),
        &plug,
        alert_url,
        metrics,
        state_file,
    ));
    recovery.set_test_panic_runs(py_int(&env_or("WAKER_TEST_PANIC_RUNS", "0")).unwrap_or(0).max(0) as u64);
    let app = Arc::new(App {
        mac_str,
        broadcast,
        probe_host,
        probe_port,
        jellyfin_port,
        trusted_proxy,
        ssh_user,
        history_since,
        hold_seconds,
        public_info_cache,
        page: page("false"),
        page_auto: page("true"),
        jf_page: JF_PAGE.replace("__COUNTDOWN__", &countdown.to_string()).replace("__VERSION__", &version).replace("__BASE__", &format!("{PUBLIC_WAKE_PREFIX}/")),
        recovery: recovery.clone(),
        ready_until: Mutex::new(f64::NEG_INFINITY),
        hold_slots: Semaphore::new(hold_slots),
        public_info: Mutex::new(None),
        stream_cache: Mutex::new(Vec::new()),
    });
    app.load_public_info();
    mono();
    let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap_or_else(|e| fail(&format!("runtime: {e}")));
    rt.block_on(async move {
        tokio::spawn(recovery.clone().supervise());
        tokio::task::yield_now().await;
        let listener = TcpListener::bind((bind.as_str(), port)).await.unwrap_or_else(|e| fail(&format!("bind {bind}:{port}: {e}")));
        println!(
            "beefy-waker listening on {bind}:{port} - page=/ gate=/gate, wake {} via {}, probe {}:{}",
            app.mac_str, app.broadcast, app.probe_host, app.probe_port
        );
        let a = app.clone();
        tokio::select! {
            _ = web::serve(listener, move |r| a.clone().handle(r)) => {}
            _ = shutdown() => {}
        }
        let _ = tokio::time::timeout(Duration::from_secs(16), recovery.shutdown()).await;
    });
}

async fn shutdown() {
    use tokio::signal::unix::{signal, SignalKind};
    let (Ok(mut term), Ok(mut int)) = (signal(SignalKind::terminate()), signal(SignalKind::interrupt())) else {
        return std::future::pending().await;
    };
    tokio::select! {
        _ = term.recv() => {}
        _ = int.recv() => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn req(h: &[(&str, &str)]) -> Req {
        Req::new("GET", "/gate", "127.0.0.1", h.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect())
    }

    #[test]
    fn tokens() {
        assert_eq!(token_param(r#"MediaBrowser Client="x", Token="abc""#), Some("abc"));
        assert_eq!(token_param(r#"token="abc""#), Some("abc"));
        assert_eq!(token_param(r#"XToken="abc""#), None);
        assert_eq!(token_param(r#"a,TOKEN="q" Token="z""#), Some("q"));
        assert_eq!(token_param(r#" Token="open"#), None);
        assert_eq!(stream_token(&req(&[("X-Emby-Token", ""), ("X-MediaBrowser-Token", "abcdefgh")])).as_deref(), Some("abcdefgh"));
        assert_eq!(stream_token(&req(&[("X-Forwarded-Uri", "/v?x=1&ApiKey=abcdefgh1&api_key=zzzzzzzzz")])).as_deref(), Some("abcdefgh1"));
        assert_eq!(stream_token(&req(&[("X-Emby-Token", "bad\"token")])), None);
    }

    #[test]
    fn client_and_keys() {
        assert_eq!(client_name(r#"MediaBrowser Client="Jellyfin Web", Device="x""#), Some("Jellyfin Web"));
        assert_eq!(client_name(r#"Client="open"#), None);
        assert_eq!(query_keys("b=1&a=&a=2&c"), vec!["a", "b", "c"]);
    }

    #[test]
    fn browser_detection() {
        assert!(is_browser(&req(&[("Accept", "TEXT/HTML")])));
        assert!(is_browser(&req(&[("Sec-Fetch-Dest", " image ")])));
        assert!(!is_browser(&req(&[("Sec-Fetch-Dest", "empty"), ("Accept", "*/*")])));
    }

    #[test]
    fn card_page_layout() {
        let p = card_page("A & B", "<p>x</p>", Some(5));
        assert!(p.contains("<meta http-equiv=\"refresh\" content=\"5\"><title>A &amp; B</title>"));
        assert!(!card_page("t", "", None).contains("refresh"));
    }

    #[test]
    fn hold_clamps() {
        assert_eq!(clamp_hold_seconds("40"), 25.0);
        assert_eq!(clamp_hold_seconds("-1"), 0.0);
        assert_eq!(clamp_hold_seconds("x"), 18.0);
        assert_eq!(clamp_hold_slots("0"), 1);
        assert_eq!(clamp_hold_slots("x"), 16);
    }
}
