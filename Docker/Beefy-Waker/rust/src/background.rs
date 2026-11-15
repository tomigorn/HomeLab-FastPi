//! Lone background requests (TV home-screen row refreshes) while beefy sleeps: classify per client, optionally do not wake.

use std::collections::HashMap;
use std::sync::Mutex;

/// A different background path from the same client within this many seconds = an app loading its home rows.
pub const BURST_SECONDS: f64 = 2.0;
const MAX_CLIENTS: usize = 1024;

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Mode {
    Off,
    Observe,
    Enforce,
}

impl Mode {
    /// (mode, valid); anything unknown falls back to observe.
    pub fn parse(v: &str) -> (Mode, bool) {
        match v.trim().to_ascii_lowercase().as_str() {
            "off" => (Mode::Off, true),
            "observe" | "" => (Mode::Observe, true),
            "enforce" => (Mode::Enforce, true),
            _ => (Mode::Observe, false),
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Mode::Off => "off",
            Mode::Observe => "observe",
            Mode::Enforce => "enforce",
        }
    }
}

/// Lower-case path with one leading slash and no trailing slash.
fn normalize(path: &str) -> String {
    format!("/{}", path.trim_matches('/')).to_ascii_lowercase()
}

/// Paths an app's home-screen rows poll without the user: resume, next up, latest.
pub fn is_background_path(method: &str, path: &str) -> bool {
    if !method.eq_ignore_ascii_case("GET") {
        return false;
    }
    let p = normalize(path);
    let segs: Vec<&str> = p.split('/').skip(1).collect();
    matches!(segs.as_slice(), ["useritems", "resume"] | ["shows", "nextup"] | ["items", "latest"] | ["users", _, "items", "latest" | "resume"])
}

/// The library-row list (`/Users/<id>/Items` with `Limit`, no `ParentId`) Moonfin sends right after its home rows.
pub fn is_followup_request(method: &str, path: &str, query: &str) -> bool {
    if !method.eq_ignore_ascii_case("GET") {
        return false;
    }
    let p = normalize(path);
    let segs: Vec<&str> = p.split('/').skip(1).collect();
    if !matches!(segs.as_slice(), ["users", _, "items"]) {
        return false;
    }
    let has = |name: &str| query.split('&').any(|kv| kv.split('=').next().unwrap_or("").eq_ignore_ascii_case(name));
    has("limit") && !has("parentid")
}

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Class {
    Foreground,
    Background,
    /// A follow-up of a skipped background request: treated as background.
    FollowUp,
}

impl Class {
    pub fn is_background(self) -> bool {
        self != Class::Foreground
    }
}

struct Seen {
    foreground: f64,
    skipped: f64,
    background: Vec<(String, f64)>,
}

pub struct Tracker {
    foreground_seconds: f64,
    followup_seconds: f64,
    clients: Mutex<HashMap<String, Seen>>,
}

impl Tracker {
    pub fn new(foreground_seconds: f64, followup_seconds: f64) -> Self {
        Tracker { foreground_seconds, followup_seconds, clients: Mutex::new(HashMap::new()) }
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, HashMap<String, Seen>> {
        self.clients.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Record the request and classify it. Background: a background path with no foreground request from the same
    /// client within the window and no other background path from it within the burst window. Follow-up: the
    /// library-row list within the follow-up window after a skipped background request of the same client.
    pub fn classify(&self, key: &str, method: &str, path: &str, query: &str, now: f64) -> Class {
        let bg_path = is_background_path(method, path);
        let norm = normalize(path);
        let mut clients = self.lock();
        if clients.len() >= MAX_CLIENTS && !clients.contains_key(key) {
            let keep = self.foreground_seconds.max(BURST_SECONDS).max(self.followup_seconds);
            clients.retain(|_, s| s.foreground.max(s.skipped).max(s.background.iter().map(|b| b.1).fold(f64::NEG_INFINITY, f64::max)) > now - keep);
            if clients.len() >= MAX_CLIENTS {
                clients.clear();
            }
        }
        let seen = clients.entry(key.to_string()).or_insert_with(|| Seen { foreground: f64::NEG_INFINITY, skipped: f64::NEG_INFINITY, background: Vec::new() });
        if !bg_path {
            if seen.skipped >= now - self.followup_seconds && is_followup_request(method, path, query) {
                return Class::FollowUp;
            }
            seen.foreground = now;
            return Class::Foreground;
        }
        seen.background.retain(|(_, t)| *t > now - BURST_SECONDS);
        let recent_fg = seen.foreground > now - self.foreground_seconds;
        let burst = seen.background.iter().any(|(p, _)| *p != norm);
        seen.background.push((norm, now));
        if recent_fg || burst { Class::Foreground } else { Class::Background }
    }

    /// A background request of this client did not (enforce) or would not (observe) wake beefy; follow-ups never re-arm.
    pub fn skipped(&self, key: &str, method: &str, path: &str, now: f64) {
        if !is_background_path(method, path) {
            return;
        }
        if let Some(seen) = self.lock().get_mut(key) {
            seen.skipped = now;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn modes() {
        assert_eq!(Mode::parse(" Enforce "), (Mode::Enforce, true));
        assert_eq!(Mode::parse("off"), (Mode::Off, true));
        assert_eq!(Mode::parse(""), (Mode::Observe, true));
        assert_eq!(Mode::parse("yes"), (Mode::Observe, false));
    }

    #[test]
    fn paths() {
        for p in ["/UserItems/Resume", "//useritems/RESUME/", "/Shows/NextUp", "/Items/Latest", "/Users/abc/Items/Latest", "/Users/abc/Items/Resume"] {
            assert!(is_background_path("GET", p), "{p}");
        }
        for p in ["/Users/abc/Items", "/Users/abc", "/UserViews", "/System/Info/Public", "/Items/x/Images/Primary", "/Users/a/b/Items/Latest"] {
            assert!(!is_background_path("GET", p), "{p}");
        }
        assert!(!is_background_path("POST", "/UserItems/Resume"));
    }

    #[test]
    fn classify_rules() {
        let t = Tracker::new(60.0, 10.0);
        let bg = |k, p, now| t.classify(k, "GET", p, "", now) == Class::Background;
        assert!(bg("a", "/UserItems/Resume", 100.0));
        assert!(bg("a", "/UserItems/Resume", 101.0));
        assert!(!bg("a", "/Shows/NextUp", 102.0));
        assert!(bg("a", "/Shows/NextUp", 110.0));
        assert!(!bg("b", "/UserViews", 200.0));
        assert!(!bg("b", "/UserItems/Resume", 259.0));
        assert!(bg("b", "/UserItems/Resume", 261.0));
        assert!(bg("c", "/UserItems/Resume", 259.5));
    }

    fn skip(t: &Tracker, key: &str, path: &str, now: f64) {
        assert_eq!(t.classify(key, "GET", path, "", now), Class::Background);
        t.skipped(key, "GET", path, now);
    }

    const ITEMS: &str = "/Users/abc/Items";
    const ITEMS_Q: &str = "Fields=x&IncludeItemTypes=Movie&Limit=24&Recursive=true";

    #[test]
    fn followup_shape() {
        assert!(is_followup_request("GET", ITEMS, ITEMS_Q));
        assert!(is_followup_request("get", "/users/abc/items/", "limit=5"));
        assert!(!is_followup_request("GET", ITEMS, "Fields=x"));
        assert!(!is_followup_request("GET", ITEMS, "Limit=5&ParentId=p"));
        assert!(!is_followup_request("GET", ITEMS, "limit=5&parentid=p"));
        assert!(!is_followup_request("POST", ITEMS, "Limit=5"));
        assert!(!is_followup_request("GET", "/Users/abc/Items/Latest", "Limit=5"));
        assert!(!is_followup_request("GET", "/UserViews", "Limit=5"));
    }

    #[test]
    fn followup_within_window_after_skip_is_background() {
        let t = Tracker::new(60.0, 10.0);
        skip(&t, "a", "/UserItems/Resume", 100.0);
        assert_eq!(t.classify("a", "GET", ITEMS, ITEMS_Q, 110.0), Class::FollowUp);
    }

    #[test]
    fn followup_after_window_wakes() {
        let t = Tracker::new(60.0, 10.0);
        skip(&t, "a", "/UserItems/Resume", 100.0);
        assert_eq!(t.classify("a", "GET", ITEMS, ITEMS_Q, 110.5), Class::Foreground);
    }

    #[test]
    fn followup_from_other_client_wakes() {
        let t = Tracker::new(60.0, 10.0);
        skip(&t, "a", "/UserItems/Resume", 100.0);
        assert_eq!(t.classify("b", "GET", ITEMS, ITEMS_Q, 101.0), Class::Foreground);
    }

    #[test]
    fn other_foreground_after_skip_wakes() {
        let t = Tracker::new(60.0, 10.0);
        skip(&t, "a", "/UserItems/Resume", 100.0);
        assert_eq!(t.classify("a", "GET", "/UserViews", "", 101.0), Class::Foreground);
        assert_eq!(t.classify("a", "GET", ITEMS, "Limit=5&ParentId=p", 101.5), Class::Foreground);
        assert_eq!(t.classify("a", "GET", ITEMS, "Fields=x", 102.0), Class::Foreground);
    }

    #[test]
    fn followup_needs_a_skip() {
        let t = Tracker::new(60.0, 10.0);
        assert_eq!(t.classify("a", "GET", "/UserItems/Resume", "", 100.0), Class::Background);
        assert_eq!(t.classify("a", "GET", ITEMS, ITEMS_Q, 101.0), Class::Foreground);
    }

    #[test]
    fn followup_is_not_a_foreground_request() {
        let t = Tracker::new(60.0, 10.0);
        skip(&t, "a", "/UserItems/Resume", 100.0);
        assert_eq!(t.classify("a", "GET", ITEMS, ITEMS_Q, 105.0), Class::FollowUp);
        assert_eq!(t.classify("a", "GET", "/Shows/NextUp", "", 106.0), Class::Background);
    }

    #[test]
    fn skipped_followup_does_not_extend_window() {
        let t = Tracker::new(60.0, 10.0);
        skip(&t, "a", "/UserItems/Resume", 100.0);
        assert_eq!(t.classify("a", "GET", ITEMS, ITEMS_Q, 109.0), Class::FollowUp);
        t.skipped("a", "GET", ITEMS, 109.0);
        assert_eq!(t.classify("a", "GET", ITEMS, ITEMS_Q, 115.0), Class::Foreground);
    }

    #[test]
    fn client_table_is_bounded() {
        let t = Tracker::new(60.0, 10.0);
        for i in 0..3000 {
            t.classify(&i.to_string(), "GET", "/UserViews", "", i as f64);
        }
        assert!(t.clients.lock().unwrap().len() <= MAX_CLIENTS);
    }
}
