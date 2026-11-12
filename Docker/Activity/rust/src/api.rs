//! HTTP routes: the page, `/api/state` (the view as JSON), `/metrics` (Prometheus text), `/health`.
//! Page and state answer only the allowed peers (Traefik), metrics only Prometheus' network.

use std::fmt::Write as _;
use std::net::{IpAddr, Ipv4Addr};

use crate::state::View;

pub const PAGE: &str = include_str!("../../www/index.html");

#[derive(Debug, PartialEq)]
pub struct Resp {
    pub status: u16,
    pub content_type: &'static str,
    pub body: String,
}

impl Resp {
    fn text(status: u16, body: &str) -> Resp {
        Resp { status, content_type: "text/plain; charset=utf-8", body: body.to_string() }
    }
}

/// IPv4 CIDR list, e.g. `172.24.255.3/32,127.0.0.1/32`.
#[derive(Clone, Debug, Default)]
pub struct Allow(Vec<(u32, u32)>);

impl Allow {
    pub fn parse(spec: &str) -> Result<Allow, String> {
        let mut out = Vec::new();
        for part in spec.split(',').map(str::trim).filter(|p| !p.is_empty()) {
            let (ip, bits) = part.split_once('/').unwrap_or((part, "32"));
            let ip: Ipv4Addr = ip.parse().map_err(|_| format!("bad address in {part}"))?;
            let bits: u32 = bits.parse().ok().filter(|b| *b <= 32).ok_or_else(|| format!("bad prefix in {part}"))?;
            let mask = if bits == 0 { 0 } else { u32::MAX << (32 - bits) };
            out.push((u32::from(ip) & mask, mask));
        }
        Ok(Allow(out))
    }

    pub fn contains(&self, ip: IpAddr) -> bool {
        let v4 = match ip {
            IpAddr::V4(v) => v,
            IpAddr::V6(v) => match v.to_ipv4_mapped() {
                Some(v) => v,
                None => return false,
            },
        };
        let n = u32::from(v4);
        self.0.iter().any(|(net, mask)| n & mask == *net)
    }
}

pub struct Access {
    pub page: Allow,
    pub metrics: Allow,
}

/// The view, the snapshot age and whether a viewer counts right now.
pub type Seen = (View, Option<i64>, bool);

/// Only the page's own `/api/state` counts as a viewer (and starts polling); `/metrics`, `/health` and the HTML never do.
pub fn is_viewer(method: &str, path: &str, peer: IpAddr, access: &Access) -> bool {
    (method == "GET" || method == "HEAD") && path == "/api/state" && access.page.contains(peer)
}

/// Connections from anyone in neither list are closed right after accept (no slot, no parsing).
pub fn admitted(peer: IpAddr, access: &Access) -> bool {
    access.page.contains(peer) || access.metrics.contains(peer)
}

#[cfg(test)]
pub fn route(method: &str, path: &str, peer: IpAddr, access: &Access, view: impl FnOnce() -> Seen) -> Resp {
    route_health(method, path, peer, access, true, view)
}

/// `poller_ok`: the poll loop runs and is not overdue; `/health` fails otherwise.
pub fn route_health(method: &str, path: &str, peer: IpAddr, access: &Access, poller_ok: bool, view: impl FnOnce() -> Seen) -> Resp {
    if method != "GET" && method != "HEAD" {
        return Resp::text(405, "GET only\n");
    }
    match path {
        "/health" if !poller_ok => Resp::text(503, "poller stopped\n"),
        "/health" => Resp::text(200, "ok\n"),
        "/" | "/index.html" | "/api/state" if !access.page.contains(peer) => Resp::text(403, "forbidden\n"),
        "/" | "/index.html" => Resp { status: 200, content_type: "text/html; charset=utf-8", body: PAGE.to_string() },
        "/api/state" => {
            let (v, _, _) = view();
            Resp { status: 200, content_type: "application/json", body: serde_json::to_string(&v).unwrap_or_else(|_| "{}".into()) }
        }
        "/metrics" if !access.metrics.contains(peer) => Resp::text(403, "forbidden\n"),
        "/metrics" => {
            let (v, age, viewer) = view();
            Resp { status: 200, content_type: "text/plain; version=0.0.4; charset=utf-8", body: metrics(&v, age, viewer) }
        }
        _ => Resp::text(404, "not found\n"),
    }
}

fn q(s: Option<crate::state::Quality>) -> &'static str {
    s.map(|q| q.label()).unwrap_or("unknown")
}

/// Prometheus text: category labels only, never titles or users.
pub fn metrics(v: &View, snapshot_age: Option<i64>, viewer: bool) -> String {
    let mut o = String::new();
    let _ = writeln!(o, "# HELP activity_viewer_active 1 while the page was viewed within the viewer window (the service polls only then).\n# TYPE activity_viewer_active gauge\nactivity_viewer_active {}", u8::from(viewer));
    if let Some(at) = v.polled_at {
        let _ = writeln!(o, "# HELP activity_last_poll_timestamp_seconds When the last poll finished (values below are from then).\n# TYPE activity_last_poll_timestamp_seconds gauge\nactivity_last_poll_timestamp_seconds {at}");
    }
    o.push_str("# HELP activity_beefy_up beefy awake per Beefy-Waker /status (1 up, 0 asleep; absent when unknown).\n# TYPE activity_beefy_up gauge\n");
    match v.beefy {
        "up" => o.push_str("activity_beefy_up 1\n"),
        "asleep" => o.push_str("activity_beefy_up 0\n"),
        _ => {}
    }
    if let Some(age) = snapshot_age {
        let _ = writeln!(o, "# HELP activity_beefy_snapshot_age_seconds Seconds since the last successful poll of beefy.\n# TYPE activity_beefy_snapshot_age_seconds gauge\nactivity_beefy_snapshot_age_seconds {age}");
    }
    if let Some(ws) = &v.watching {
        let mut groups: std::collections::BTreeMap<(&str, &str, &str), u32> = Default::default();
        for s in ws {
            *groups.entry((s.kind.label(), q(s.quality), s.mode.label())).or_default() += s.n;
        }
        let _ = writeln!(o, "# HELP activity_watching_streams Jellyfin streams now (0 while beefy sleeps).\n# TYPE activity_watching_streams gauge\nactivity_watching_streams {}", ws.iter().map(|s| s.n).sum::<u32>());
        o.push_str("# HELP activity_streams Jellyfin streams by kind, quality and playback mode.\n# TYPE activity_streams gauge\n");
        for ((k, ql, m), n) in groups {
            let _ = writeln!(o, "activity_streams{{kind=\"{k}\",quality=\"{ql}\",mode=\"{m}\"}} {n}");
        }
    }
    if let Some(ds) = &v.downloads {
        o.push_str("# HELP activity_downloads Titles in the download pipeline by state, kind and quality (last known while beefy sleeps).\n# TYPE activity_downloads gauge\n");
        for d in ds {
            let _ = writeln!(o, "activity_downloads{{state=\"{}\",kind=\"{}\",quality=\"{}\"}} {}", d.state.label(), d.kind.label(), q(d.quality), d.items);
        }
    }
    if let Some(l) = &v.listening {
        let _ = writeln!(o, "# HELP activity_listening_sessions Audiobookshelf sessions synced in the last 5 minutes.\n# TYPE activity_listening_sessions gauge\nactivity_listening_sessions {}", l.sessions);
    }
    if let Some(a) = &v.audiobook_downloads {
        let _ = writeln!(o, "# HELP activity_audiobook_downloads qBittorrent (mouse) category abr torrents by state.\n# TYPE activity_audiobook_downloads gauge\nactivity_audiobook_downloads{{state=\"downloading\"}} {}\nactivity_audiobook_downloads{{state=\"queued\"}} {}", a.downloading, a.queued);
    }
    o
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::{tests::{downloads_part, streams_part}, view, Local, Polled, WakerState};

    const NOW: i64 = 1_794_430_000;

    fn access() -> Access {
        Access { page: Allow::parse("172.24.255.3/32,127.0.0.1").unwrap(), metrics: Allow::parse("10.24.40.0/29").unwrap() }
    }
    fn ip(s: &str) -> IpAddr {
        s.parse().unwrap()
    }
    fn live() -> Seen {
        let l = Local { listening: Some(2), abr_downloading: Some(1), abr_queued: Some(0) };
        (view(NOW, Some(&streams_part(NOW - 10)), Some(&downloads_part(NOW - 10)), WakerState::Up, &l, Polled { at: Some(NOW - 10), ..Polled::default() }), Some(10), true)
    }

    #[test]
    fn metrics_lists_categories_without_titles() {
        let (v, age, viewer) = live();
        let m = metrics(&v, age, viewer);
        assert!(m.contains("activity_viewer_active 1\n"), "{m}");
        assert!(m.contains("activity_last_poll_timestamp_seconds 1794429990\n"), "{m}");
        assert!(m.contains("activity_beefy_up 1\n"), "{m}");
        assert!(m.contains("activity_beefy_snapshot_age_seconds 10\n"), "{m}");
        assert!(m.contains("activity_streams{kind=\"Episode\",quality=\"1080p SDR\",mode=\"direct play\"} 1\n"), "{m}");
        assert!(m.contains("activity_watching_streams 1\n"), "{m}");
        assert!(m.contains("activity_downloads{state=\"downloading\",kind=\"Movie\",quality=\"4K HDR\"} 1\n"), "{m}");
        assert!(m.contains("activity_listening_sessions 2\n"), "{m}");
        assert!(m.contains("activity_audiobook_downloads{state=\"downloading\"} 1\n"), "{m}");
        for line in m.lines().filter(|l| !l.starts_with('#')) {
            let labels = line.split_once('{').map(|(_, r)| r.split_once('}').unwrap().0).unwrap_or("");
            for pair in labels.split(',').filter(|p| !p.is_empty()) {
                let k = pair.split_once('=').unwrap().0;
                assert!(["kind", "quality", "mode", "state"].contains(&k), "unexpected label {k} in {line}");
            }
        }
        let asleep = view(NOW, Some(&streams_part(NOW - 999)), Some(&downloads_part(NOW - 999)), WakerState::Down, &Local::default(), Polled::default());
        let m = metrics(&asleep, Some(999), false);
        assert!(m.contains("activity_viewer_active 0\n") && !m.contains("activity_last_poll_timestamp_seconds"), "{m}");
        assert!(m.contains("activity_beefy_up 0\n") && m.contains("activity_watching_streams 0\n") && !m.contains("activity_streams{"), "{m}");
    }

    #[test]
    fn page_and_state_only_from_allowed_peers() {
        let a = access();
        assert_eq!(route("GET", "/", ip("172.24.255.3"), &a, live).status, 200);
        assert!(route("GET", "/", ip("172.24.255.3"), &a, live).body.contains("<html"));
        let s = route("GET", "/api/state", ip("127.0.0.1"), &a, live);
        assert_eq!((s.status, s.content_type), (200, "application/json"));
        assert!(s.body.contains(r#""beefy":"up""#), "{}", s.body);
        assert_eq!(route("GET", "/api/state", ip("172.24.0.6"), &a, live).status, 403, "another container on traefik_proxy");
        assert_eq!(route("GET", "/", ip("::ffff:172.24.0.6"), &a, live).status, 403);
        assert_eq!(route("GET", "/metrics", ip("172.24.255.3"), &a, live).status, 403);
        assert_eq!(route("GET", "/metrics", ip("10.24.40.3"), &a, live).status, 200);
        assert_eq!(route("GET", "/health", ip("172.24.0.6"), &a, live).status, 200);
    }

    #[test]
    fn health_fails_when_the_poller_is_dead() {
        let a = access();
        assert_eq!(route_health("GET", "/health", ip("127.0.0.1"), &a, false, live).status, 503);
        assert_eq!(route_health("GET", "/health", ip("127.0.0.1"), &a, true, live).status, 200);
        assert_eq!(route_health("GET", "/api/state", ip("127.0.0.1"), &a, false, live).status, 200, "the page still answers");
    }

    #[test]
    fn peers_in_neither_list_are_dropped() {
        let a = access();
        assert!(admitted(ip("172.24.255.3"), &a));
        assert!(admitted(ip("10.24.40.3"), &a));
        assert!(admitted(ip("127.0.0.1"), &a));
        assert!(!admitted(ip("172.24.0.6"), &a), "another container on traefik_proxy");
        assert!(!admitted(ip("::1"), &a));
    }

    #[test]
    fn only_the_state_from_the_page_counts_as_viewer() {
        let a = access();
        assert!(is_viewer("GET", "/api/state", ip("172.24.255.3"), &a));
        assert!(is_viewer("HEAD", "/api/state", ip("127.0.0.1"), &a));
        assert!(!is_viewer("GET", "/metrics", ip("10.24.40.3"), &a), "Prometheus is no viewer");
        assert!(!is_viewer("GET", "/health", ip("127.0.0.1"), &a), "the healthcheck is no viewer");
        assert!(!is_viewer("GET", "/", ip("172.24.255.3"), &a), "the HTML alone is no viewer");
        assert!(!is_viewer("GET", "/api/state", ip("172.24.0.6"), &a), "a refused peer is no viewer");
        assert!(!is_viewer("POST", "/api/state", ip("127.0.0.1"), &a));
    }

    #[test]
    fn unknown_paths_and_methods() {
        let a = access();
        assert_eq!(route("GET", "/ingest", ip("127.0.0.1"), &a, live).status, 404);
        assert_eq!(route("POST", "/api/state", ip("127.0.0.1"), &a, live).status, 405);
        assert_eq!(route("PUT", "/", ip("127.0.0.1"), &a, live).status, 405);
    }

    #[test]
    fn allow_lists() {
        assert!(Allow::parse("10.0.0.0/8").unwrap().contains(ip("10.1.2.3")));
        assert!(!Allow::parse("10.0.0.0/8").unwrap().contains(ip("11.0.0.1")));
        assert!(Allow::parse("1.2.3.4/33").is_err());
        assert!(Allow::parse("nope").is_err());
        assert!(!Allow::parse("").unwrap().contains(ip("127.0.0.1")));
    }
}
