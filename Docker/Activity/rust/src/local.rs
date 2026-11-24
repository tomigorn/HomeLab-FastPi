//! fastpi-local audiobook figures: Audiobookshelf listening sessions, the qBittorrent category `abr` (mouse) and the request counts of the Audiobook-Requests importer.
//! qBittorrent is read through Traefik's internal route, which qBittorrent lets in without a login and which allows only this one GET.

use std::path::PathBuf;
use std::time::Duration;

use serde::Deserialize;

use crate::client::{self, BaseUrl};
use crate::influx::Influx;
use crate::state::{Abr, FastpiLoad, ListenMode, Local, Requests};

pub const TIMEOUT: Duration = Duration::from_secs(3);
/// An open ABS session counts as listening when its progress was synced within this window (ABS keeps stale sessions open for 36 h).
pub const ACTIVE_MS: i64 = 5 * 60 * 1000;
const LIMIT: usize = 4 << 20;
const DOWNLOADING: [&str; 9] = ["downloading", "stalledDL", "metaDL", "forcedDL", "forcedMetaDL", "allocating", "checkingDL", "moving", "checkingResumeData"];
const QUEUED: [&str; 1] = ["queuedDL"];
const PAUSED: [&str; 2] = ["stoppedDL", "pausedDL"];
const PROBLEM: [&str; 2] = ["error", "missingFiles"];

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "camelCase")]
struct OpenSessions {
    sessions: Option<Vec<AbsSession>>,
    share_sessions: Option<Vec<AbsSession>>,
}

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "camelCase")]
struct AbsSession {
    updated_at: Option<i64>,
    play_method: Option<i64>,
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct Torrent {
    state: Option<String>,
    eta: Option<i64>,
    amount_left: Option<u64>,
}

/// qBittorrent's ETA for "never" (100 days).
const ETA_NEVER: i64 = 8_640_000;

/// Audiobookshelf `GET /api/sessions/open`: the play method of each session (and share session) synced within ACTIVE_MS, sorted.
pub fn count_abs(body: &[u8], now_ms: i64) -> Result<Vec<ListenMode>, String> {
    let o: OpenSessions = serde_json::from_slice(body).map_err(|_| "unreadable answer".to_string())?;
    let mut modes: Vec<ListenMode> = o
        .sessions
        .iter()
        .flatten()
        .chain(o.share_sessions.iter().flatten())
        .filter(|s| s.updated_at.is_some_and(|t| now_ms - t < ACTIVE_MS))
        .map(|s| match s.play_method {
            Some(0) => ListenMode::DirectPlay,
            Some(1) => ListenMode::DirectStream,
            Some(2) => ListenMode::Transcode,
            Some(3) => ListenMode::Local,
            _ => ListenMode::Other,
        })
        .collect();
    modes.sort();
    Ok(modes)
}

/// qBittorrent `GET /api/v2/torrents/info?category=abr`: unfinished torrents by state (seeding and finished ones are not counted).
pub fn count_qbit(body: &[u8]) -> Result<Abr, String> {
    let t: Vec<Torrent> = serde_json::from_slice(body).map_err(|_| "unreadable answer".to_string())?;
    let count = |set: &[&str]| t.iter().filter(|t| t.state.as_deref().is_some_and(|s| set.contains(&s))).count() as u32;
    let dl = || t.iter().filter(|t| t.state.as_deref().is_some_and(|s| DOWNLOADING.contains(&s)));
    let eta = dl().filter_map(|t| t.eta).filter(|e| (0..ETA_NEVER).contains(e)).max().map(|e| e as u64);
    let left = dl().filter_map(|t| t.amount_left).sum();
    Ok(Abr { downloading: count(&DOWNLOADING), queued: count(&QUEUED), paused: count(&PAUSED), problem: count(&PROBLEM), eta, left })
}

/// The importer's `GET /counts` (through Traefik's internal route): `{"open":n,"failed":n}`, nothing else.
pub fn count_requests(body: &[u8]) -> Result<Requests, String> {
    serde_json::from_slice(body).map_err(|_| "unreadable answer".to_string())
}

fn read_secret(path: &PathBuf) -> Result<String, String> {
    let s = std::fs::read_to_string(path).map_err(|_| "secret file unreadable".to_string())?;
    let s = s.trim().to_string();
    if s.is_empty() { Err("secret file empty".into()) } else { Ok(s) }
}

pub struct Sources {
    pub abs: Option<(BaseUrl, PathBuf)>,
    pub qbit: Option<BaseUrl>,
    pub requests: Option<BaseUrl>,
    pub influx: Option<Influx>,
}

impl Sources {
    pub fn new(abs: Option<(BaseUrl, PathBuf)>, qbit: Option<BaseUrl>, requests: Option<BaseUrl>, influx: Option<Influx>) -> Sources {
        Sources { abs, qbit, requests, influx }
    }

    async fn requests(&self) -> Result<Requests, String> {
        let base = self.requests.as_ref().ok_or("not configured")?;
        let body = client::get(base, "/counts", &[("accept", "application/json")], LIMIT, TIMEOUT).await?;
        count_requests(&body)
    }

    async fn load(&self) -> Result<FastpiLoad, String> {
        self.influx.as_ref().ok_or("not configured")?.load().await
    }

    async fn abs(&self, now_ms: i64) -> Result<Vec<ListenMode>, String> {
        let (base, key_file) = self.abs.as_ref().ok_or("not configured")?;
        let auth = format!("Bearer {}", read_secret(key_file)?);
        let body = client::get(base, "/api/sessions/open", &[("authorization", &auth), ("accept", "application/json")], LIMIT, TIMEOUT).await?;
        count_abs(&body, now_ms)
    }

    async fn qbit(&self) -> Result<Abr, String> {
        let base = self.qbit.as_ref().ok_or("not configured")?;
        let body = client::get(base, "/api/v2/torrents/info?category=abr", &[("accept", "application/json")], LIMIT, TIMEOUT).await?;
        count_qbit(&body)
    }

    /// One refresh of the sources side by side; a failing source is None (and its reason returned for a log line), the others still count.
    pub async fn refresh(&self, now_ms: i64) -> (Local, Vec<String>) {
        let mut errors = Vec::new();
        let (abs, qbit, requests, load) = tokio::join!(self.abs(now_ms), self.qbit(), self.requests(), async {
            match &self.influx {
                Some(_) => Some(self.load().await),
                None => None,
            }
        });
        let listening = match abs {
            Ok(n) => Some(n),
            Err(e) => {
                errors.push(format!("audiobookshelf: {e}"));
                None
            }
        };
        let abr = match qbit {
            Ok(a) => Some(a),
            Err(e) => {
                errors.push(format!("qbittorrent: {e}"));
                None
            }
        };
        let requests = match requests {
            Ok(r) => Some(r),
            Err(e) => {
                errors.push(format!("audiobook-requests: {e}"));
                None
            }
        };
        let load = match load {
            Some(Ok(l)) => Some(l),
            Some(Err(e)) => {
                errors.push(format!("influxdb: {e}"));
                None
            }
            None => None,
        };
        (Local { listening, abr, requests, load }, errors)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;

    const ABS: &str = include_str!("../fixtures/abs-sessions.json");
    const QBIT: &str = include_str!("../fixtures/qbit-abr.json");

    #[test]
    fn request_counts_read() {
        assert_eq!(count_requests(br#"{"open":2,"failed":0}"#), Ok(Requests { open: 2, failed: 0 }));
        assert!(count_requests(b"{}").is_err(), "a 502 body is not zero requests");
        assert!(count_requests(br#"{"open":-1,"failed":0}"#).is_err());
    }

    #[test]
    fn abs_sessions_counted() {
        assert_eq!(count_abs(ABS.as_bytes(), 60_000), Ok(vec![ListenMode::DirectPlay, ListenMode::Transcode, ListenMode::Other]), "two sessions and one share session synced a minute ago (play methods 0, 2, unknown 7), one an hour ago");
        assert_eq!(count_abs(ABS.as_bytes(), 10 * 60_000), Ok(vec![]));
        assert_eq!(count_abs(br#"{"sessions":[],"shareSessions":null}"#, 0), Ok(vec![]));
        assert!(count_abs(b"Unauthorized", 0).is_err());
    }

    #[test]
    fn qbit_abr_downloading_and_queued_counted() {
        assert_eq!(count_qbit(QBIT.as_bytes()), Ok(Abr { downloading: 5, queued: 1, paused: 2, problem: 2, eta: Some(600), left: 170_000_000 }), "eta: the longest finite one of the downloading; left: their amount_left; downloading + stalledDL + metaDL + moving + checkingResumeData; queuedDL; stoppedDL + pausedDL; error + missingFiles; seeding ignored");
        assert_eq!(count_qbit(b"[]"), Ok(Abr::default()));
        assert!(count_qbit(b"Forbidden").is_err());
    }

    /// Fake Traefik route to qBittorrent: only GET /activity/qbit/api/v2/torrents/info?category=abr without a cookie, anything else 403.
    async fn fake_qbit() -> u16 {
        let l = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = l.local_addr().unwrap().port();
        tokio::spawn(async move {
            loop {
                let Ok((mut s, _)) = l.accept().await else { return };
                tokio::spawn(async move {
                    let mut buf = vec![0u8; 8192];
                    let n = s.read(&mut buf).await.unwrap_or(0);
                    let req = String::from_utf8_lossy(&buf[..n]).to_string();
                    let ok = |b: &str| format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", b.len(), b);
                    let resp = if req.starts_with("GET /activity/qbit/api/v2/torrents/info?category=abr ") && !req.to_lowercase().contains("\r\ncookie:") {
                        ok(QBIT)
                    } else if req.starts_with("GET /activity/abr/counts ") {
                        ok(r#"{"open":3,"failed":1}"#)
                    } else {
                        "HTTP/1.1 403 Forbidden\r\nContent-Length: 9\r\nConnection: close\r\n\r\nForbidden".to_string()
                    };
                    let _ = s.write_all(resp.as_bytes()).await;
                });
            }
        });
        port
    }

    #[tokio::test]
    async fn abs_unreachable_gives_none_rest_ok() {
        let dir = std::env::temp_dir().join(format!("activity-local-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("key"), "fixture-key\n").unwrap();
        let port = fake_qbit().await;
        let src = Sources::new(
            Some((BaseUrl::parse("http://127.0.0.1:9").unwrap(), dir.join("key"))),
            Some(BaseUrl::parse(&format!("http://127.0.0.1:{port}/activity/qbit")).unwrap()),
            Some(BaseUrl::parse(&format!("http://127.0.0.1:{port}/activity/abr")).unwrap()),
            None,
        );
        let (local, errors) = src.refresh(0).await;
        assert_eq!(local, Local { listening: None, abr: Some(Abr { downloading: 5, queued: 1, paused: 2, problem: 2, eta: Some(600), left: 170_000_000 }), requests: Some(Requests { open: 3, failed: 1 }), load: None }, "{errors:?}");
        assert_eq!(errors.len(), 1);
        assert!(errors[0].starts_with("audiobookshelf: "), "{errors:?}");
        let refused = Sources::new(None, Some(BaseUrl::parse(&format!("http://127.0.0.1:{port}/elsewhere")).unwrap()), Some(BaseUrl::parse(&format!("http://127.0.0.1:{port}/nowhere")).unwrap()), None);
        let (local, errors) = refused.refresh(0).await;
        assert_eq!(local, Local::default(), "route refused = unavailable, no crash");
        assert!(errors.contains(&"qbittorrent: HTTP 403".to_string()), "{errors:?}");
        assert!(errors.contains(&"audiobook-requests: HTTP 403".to_string()), "{errors:?}");
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
