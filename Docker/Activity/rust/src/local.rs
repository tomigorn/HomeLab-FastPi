//! fastpi-local audiobook figures: Audiobookshelf listening sessions and the qBittorrent category `abr` (mouse).

use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Duration;

use serde::Deserialize;

use crate::client::{self, BaseUrl};
use crate::state::Local;

pub const TIMEOUT: Duration = Duration::from_secs(3);
/// An open ABS session counts as listening when its progress was synced within this window (ABS keeps stale sessions open for 36 h).
pub const ACTIVE_MS: i64 = 5 * 60 * 1000;
const LIMIT: usize = 4 << 20;
const DOWNLOADING: [&str; 7] = ["downloading", "stalledDL", "metaDL", "forcedDL", "forcedMetaDL", "allocating", "checkingDL"];
const QUEUED: [&str; 1] = ["queuedDL"];

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
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct Torrent {
    state: Option<String>,
}

/// Audiobookshelf `GET /api/sessions/open`: sessions (and share sessions) synced within ACTIVE_MS.
pub fn count_abs(body: &[u8], now_ms: i64) -> Result<u32, String> {
    let o: OpenSessions = serde_json::from_slice(body).map_err(|_| "unreadable answer".to_string())?;
    let n = o.sessions.iter().flatten().chain(o.share_sessions.iter().flatten()).filter(|s| s.updated_at.is_some_and(|t| now_ms - t < ACTIVE_MS)).count();
    Ok(n as u32)
}

/// qBittorrent `GET /api/v2/torrents/info?category=abr`: (downloading, queued).
pub fn count_qbit(body: &[u8]) -> Result<(u32, u32), String> {
    let t: Vec<Torrent> = serde_json::from_slice(body).map_err(|_| "unreadable answer".to_string())?;
    let count = |set: &[&str]| t.iter().filter(|t| t.state.as_deref().is_some_and(|s| set.contains(&s))).count() as u32;
    Ok((count(&DOWNLOADING), count(&QUEUED)))
}

/// `SID=<value>` from a qBittorrent login `Set-Cookie`.
pub fn sid_from_set_cookie(cookies: &[String]) -> Option<String> {
    cookies.iter().find_map(|c| {
        let first = c.split(';').next()?.trim();
        let v = first.strip_prefix("SID=")?;
        (!v.is_empty()).then(|| v.to_string())
    })
}

fn form_encode(s: &str) -> String {
    s.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' => (b as char).to_string(),
            _ => format!("%{b:02X}"),
        })
        .collect()
}

fn read_secret(path: &PathBuf) -> Result<String, String> {
    let s = std::fs::read_to_string(path).map_err(|_| "secret file unreadable".to_string())?;
    let s = s.trim().to_string();
    if s.is_empty() { Err("secret file empty".into()) } else { Ok(s) }
}

pub struct Sources {
    pub abs: Option<(BaseUrl, PathBuf)>,
    pub qbit: Option<(BaseUrl, PathBuf, String)>,
    sid: Mutex<Option<String>>,
}

impl Sources {
    pub fn new(abs: Option<(BaseUrl, PathBuf)>, qbit: Option<(BaseUrl, PathBuf, String)>) -> Sources {
        Sources { abs, qbit, sid: Mutex::new(None) }
    }

    async fn abs(&self, now_ms: i64) -> Result<u32, String> {
        let (base, key_file) = self.abs.as_ref().ok_or("not configured")?;
        let auth = format!("Bearer {}", read_secret(key_file)?);
        let body = client::get(base, "/api/sessions/open", &[("authorization", &auth), ("accept", "application/json")], LIMIT, TIMEOUT).await?;
        count_abs(&body, now_ms)
    }

    async fn login(&self, base: &BaseUrl, pass_file: &PathBuf, user: &str) -> Result<String, String> {
        let body = format!("username={}&password={}", form_encode(user), form_encode(&read_secret(pass_file)?));
        let referer = format!("http://{}:{}", base.host, base.port);
        let r = client::request(
            "POST",
            &base.host,
            base.port,
            &format!("{}/api/v2/auth/login", base.base),
            &[("content-type", "application/x-www-form-urlencoded"), ("referer", &referer)],
            Some(body.into_bytes()),
            1024,
            TIMEOUT,
        )
        .await?;
        if r.status != 200 {
            return Err(format!("login HTTP {}", r.status));
        }
        sid_from_set_cookie(&r.set_cookies).ok_or_else(|| "login refused".to_string())
    }

    async fn qbit(&self) -> Result<(u32, u32), String> {
        let (base, pass_file, user) = self.qbit.as_ref().ok_or("not configured")?;
        let cached = self.sid.lock().map_err(|_| "lock")?.clone();
        let sid = match cached {
            Some(s) => s,
            None => {
                let s = self.login(base, pass_file, user).await?;
                *self.sid.lock().map_err(|_| "lock")? = Some(s.clone());
                s
            }
        };
        let cookie = format!("SID={sid}");
        match client::get(base, "/api/v2/torrents/info?category=abr", &[("cookie", &cookie), ("accept", "application/json")], LIMIT, TIMEOUT).await {
            Ok(body) => count_qbit(&body),
            Err(e) => {
                if e == "HTTP 403" {
                    *self.sid.lock().map_err(|_| "lock")? = None;
                }
                Err(e)
            }
        }
    }

    /// One refresh of both sources; a failing source is None (and its reason returned for a log line), the other still counts.
    pub async fn refresh(&self, now_ms: i64) -> (Local, Vec<String>) {
        let mut errors = Vec::new();
        let listening = match self.abs(now_ms).await {
            Ok(n) => Some(n),
            Err(e) => {
                errors.push(format!("audiobookshelf: {e}"));
                None
            }
        };
        let (abr_downloading, abr_queued) = match self.qbit().await {
            Ok((d, q)) => (Some(d), Some(q)),
            Err(e) => {
                errors.push(format!("qbittorrent: {e}"));
                (None, None)
            }
        };
        (Local { listening, abr_downloading, abr_queued }, errors)
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
    fn abs_sessions_counted() {
        assert_eq!(count_abs(ABS.as_bytes(), 60_000), Ok(3), "two sessions and one share session synced a minute ago, one an hour ago");
        assert_eq!(count_abs(ABS.as_bytes(), 10 * 60_000), Ok(0));
        assert_eq!(count_abs(br#"{"sessions":[],"shareSessions":null}"#, 0), Ok(0));
        assert!(count_abs(b"Unauthorized", 0).is_err());
    }

    #[test]
    fn qbit_abr_downloading_and_queued_counted() {
        assert_eq!(count_qbit(QBIT.as_bytes()), Ok((3, 1)), "downloading + stalledDL + metaDL; queuedDL; seeding ignored");
        assert_eq!(count_qbit(b"[]"), Ok((0, 0)));
        assert!(count_qbit(b"Forbidden").is_err());
    }

    #[test]
    fn sid_cookie() {
        assert_eq!(sid_from_set_cookie(&["SID=abc123; HttpOnly; path=/; SameSite=Strict".into()]), Some("abc123".into()));
        assert_eq!(sid_from_set_cookie(&["other=1".into()]), None);
        assert_eq!(form_encode("p@ss w&rd"), "p%40ss%20w%26rd");
    }

    /// Fake qBittorrent: login answers a SID cookie, torrents/info needs it.
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
                    let resp = if req.starts_with("POST /api/v2/auth/login") && req.contains("password=fixture-pass") {
                        "HTTP/1.1 200 OK\r\nSet-Cookie: SID=fakesid; HttpOnly; path=/\r\nContent-Length: 3\r\nConnection: close\r\n\r\nOk.".to_string()
                    } else if req.starts_with("GET /api/v2/torrents/info?category=abr") && req.to_lowercase().contains("cookie: sid=fakesid") {
                        format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", QBIT.len(), QBIT)
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
        std::fs::write(dir.join("pass"), "fixture-pass\n").unwrap();
        let port = fake_qbit().await;
        let src = Sources::new(
            Some((BaseUrl::parse("http://127.0.0.1:9").unwrap(), dir.join("key"))),
            Some((BaseUrl::parse(&format!("http://127.0.0.1:{port}")).unwrap(), dir.join("pass"), "admin".into())),
        );
        let (local, errors) = src.refresh(0).await;
        assert_eq!(local, Local { listening: None, abr_downloading: Some(3), abr_queued: Some(1) });
        assert_eq!(errors.len(), 1);
        assert!(errors[0].starts_with("audiobookshelf: "), "{errors:?}");
        let (again, _) = src.refresh(0).await;
        assert_eq!(again.abr_downloading, Some(3), "cached session id still works");
        let none = Sources::new(None, Some((BaseUrl::parse(&format!("http://127.0.0.1:{port}")).unwrap(), dir.join("missing"), "admin".into())));
        assert_eq!(none.refresh(0).await.0, Local::default(), "missing credential = unavailable, no crash");
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
