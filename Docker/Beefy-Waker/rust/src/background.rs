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

#[derive(Default)]
struct Seen {
    foreground: f64,
    background: Vec<(String, f64)>,
}

pub struct Tracker {
    foreground_seconds: f64,
    clients: Mutex<HashMap<String, Seen>>,
}

impl Tracker {
    pub fn new(foreground_seconds: f64) -> Self {
        Tracker { foreground_seconds, clients: Mutex::new(HashMap::new()) }
    }

    /// Record the request and say whether it is background: a background path with no foreground request from
    /// the same client within the window and no other background path from it within the burst window.
    pub fn classify(&self, key: &str, method: &str, path: &str, now: f64) -> bool {
        let bg_path = is_background_path(method, path);
        let norm = normalize(path);
        let mut clients = self.clients.lock().unwrap_or_else(|e| e.into_inner());
        if clients.len() >= MAX_CLIENTS && !clients.contains_key(key) {
            let keep = self.foreground_seconds.max(BURST_SECONDS);
            clients.retain(|_, s| s.foreground.max(s.background.iter().map(|b| b.1).fold(f64::NEG_INFINITY, f64::max)) > now - keep);
            if clients.len() >= MAX_CLIENTS {
                clients.clear();
            }
        }
        let seen = clients.entry(key.to_string()).or_insert_with(|| Seen { foreground: f64::NEG_INFINITY, background: Vec::new() });
        if !bg_path {
            seen.foreground = now;
            return false;
        }
        seen.background.retain(|(_, t)| *t > now - BURST_SECONDS);
        let recent_fg = seen.foreground > now - self.foreground_seconds;
        let burst = seen.background.iter().any(|(p, _)| *p != norm);
        seen.background.push((norm, now));
        !(recent_fg || burst)
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
        let t = Tracker::new(60.0);
        assert!(t.classify("a", "GET", "/UserItems/Resume", 100.0));
        assert!(t.classify("a", "GET", "/UserItems/Resume", 101.0));
        assert!(!t.classify("a", "GET", "/Shows/NextUp", 102.0));
        assert!(t.classify("a", "GET", "/Shows/NextUp", 110.0));
        assert!(!t.classify("b", "GET", "/UserViews", 200.0));
        assert!(!t.classify("b", "GET", "/UserItems/Resume", 259.0));
        assert!(t.classify("b", "GET", "/UserItems/Resume", 261.0));
        assert!(t.classify("c", "GET", "/UserItems/Resume", 259.5));
    }

    #[test]
    fn client_table_is_bounded() {
        let t = Tracker::new(60.0);
        for i in 0..3000 {
            t.classify(&i.to_string(), "GET", "/UserViews", i as f64);
        }
        assert!(t.clients.lock().unwrap().len() <= MAX_CLIENTS);
    }
}
