//! Category values, the anonymous snapshot of beefy, the staleness rule and the view the page reads.

use std::path::Path;

use serde::{Deserialize, Serialize};

/// beefy data counts only while the last successful poll is younger than this.
pub const STALE_AFTER: i64 = 90;
pub const SNAPSHOT_VERSION: u32 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub enum Kind {
    Movie,
    Episode,
    Anime,
    Audiobook,
    Other,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub enum Quality {
    #[serde(rename = "4K HDR")]
    Uhd4kHdr,
    #[serde(rename = "4K SDR")]
    Uhd4kSdr,
    #[serde(rename = "1080p HDR")]
    Fhd1080Hdr,
    #[serde(rename = "1080p SDR")]
    Fhd1080Sdr,
    #[serde(rename = "720p")]
    Hd720,
    #[serde(rename = "SD")]
    Sd,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub enum Mode {
    #[serde(rename = "direct play")]
    DirectPlay,
    #[serde(rename = "direct stream")]
    DirectStream,
    #[serde(rename = "transcode")]
    Transcode,
    #[serde(rename = "transcode (audio)")]
    TranscodeAudio,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub enum DlState {
    #[serde(rename = "downloading")]
    Downloading,
    #[serde(rename = "importing")]
    Importing,
    #[serde(rename = "waiting for night")]
    WaitingNight,
    #[serde(rename = "waiting for release")]
    WaitingRelease,
    #[serde(rename = "problem")]
    Problem,
}

impl Quality {
    /// Resolution bucket from the frame size (height, or width for letterboxed films) plus dynamic range.
    pub fn from_frame(height: u32, width: u32, hdr: bool) -> Option<Quality> {
        if height == 0 && width == 0 {
            return None;
        }
        let q = if height >= 2000 || width >= 3800 {
            if hdr { Quality::Uhd4kHdr } else { Quality::Uhd4kSdr }
        } else if height >= 1000 || width >= 1900 {
            if hdr { Quality::Fhd1080Hdr } else { Quality::Fhd1080Sdr }
        } else if height >= 700 || width >= 1260 {
            Quality::Hd720
        } else {
            Quality::Sd
        };
        Some(q)
    }

    pub fn label(self) -> &'static str {
        match self {
            Quality::Uhd4kHdr => "4K HDR",
            Quality::Uhd4kSdr => "4K SDR",
            Quality::Fhd1080Hdr => "1080p HDR",
            Quality::Fhd1080Sdr => "1080p SDR",
            Quality::Hd720 => "720p",
            Quality::Sd => "SD",
        }
    }
}

impl Kind {
    pub fn label(self) -> &'static str {
        match self {
            Kind::Movie => "Movie",
            Kind::Episode => "Episode",
            Kind::Anime => "Anime",
            Kind::Audiobook => "Audiobook",
            Kind::Other => "Other",
        }
    }
}

impl Mode {
    pub fn label(self) -> &'static str {
        match self {
            Mode::DirectPlay => "direct play",
            Mode::DirectStream => "direct stream",
            Mode::Transcode => "transcode",
            Mode::TranscodeAudio => "transcode (audio)",
        }
    }
}

impl DlState {
    pub fn label(self) -> &'static str {
        match self {
            DlState::Downloading => "downloading",
            DlState::Importing => "importing",
            DlState::WaitingNight => "waiting for night",
            DlState::WaitingRelease => "waiting for release",
            DlState::Problem => "problem",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Stream {
    pub kind: Kind,
    pub quality: Option<Quality>,
    pub mode: Mode,
    pub paused: bool,
    pub n: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Download {
    pub state: DlState,
    pub kind: Kind,
    pub quality: Option<Quality>,
    pub items: u32,
    pub seasons: u32,
    pub episodes: u32,
}

/// One successful poll of beefy, already aggregated: categories and counts only.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    pub v: u32,
    pub at: i64,
    pub streams: Vec<Stream>,
    pub downloads: Vec<Download>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WakerState {
    Up,
    Down,
    Unknown,
}

/// fastpi-local audiobook figures; None = source unavailable.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Local {
    pub listening: Option<u32>,
    pub abr_downloading: Option<u32>,
    pub abr_queued: Option<u32>,
}

#[derive(Debug, PartialEq, Serialize)]
pub struct Listening {
    pub sessions: u32,
}

#[derive(Debug, PartialEq, Serialize)]
pub struct AudiobookDownloads {
    pub downloading: u32,
    pub queued: u32,
}

#[derive(Debug, PartialEq, Serialize)]
pub struct View {
    pub now: i64,
    /// "up" | "asleep" | "unknown" (Waker /status)
    pub beefy: &'static str,
    /// "live" (fresh and trusted) | "stale" (last known only) | "none" (never polled)
    pub beefy_data: &'static str,
    /// None = unavailable (awake without fresh data, or Waker state unknown); empty while asleep = nobody watching
    pub watching: Option<Vec<Stream>>,
    /// None = never polled
    pub downloads: Option<Vec<Download>>,
    /// set when `downloads` is the last known state, not live
    pub downloads_as_of: Option<i64>,
    pub listening: Option<Listening>,
    pub audiobook_downloads: Option<AudiobookDownloads>,
    /// when the last poll finished (None = no poll since the start)
    pub polled_at: Option<i64>,
    /// the Waker says up but the last poll of the beefy gate failed
    pub gate_failed: bool,
}

/// What the last poll left behind besides the data.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Polled {
    pub at: Option<i64>,
    pub gate_failed: bool,
}

pub fn view(now: i64, snap: Option<&Snapshot>, waker: WakerState, local: &Local, polled: Polled) -> View {
    let fresh = snap.is_some_and(|s| now - s.at < STALE_AFTER);
    let trusted = fresh && waker == WakerState::Up;
    let watching = match (trusted, waker) {
        (true, _) => snap.map(|s| s.streams.clone()),
        (false, WakerState::Down) => Some(Vec::new()),
        _ => None,
    };
    let audiobook_downloads = match (local.abr_downloading, local.abr_queued) {
        (Some(downloading), Some(queued)) => Some(AudiobookDownloads { downloading, queued }),
        _ => None,
    };
    View {
        now,
        beefy: match waker {
            WakerState::Up => "up",
            WakerState::Down => "asleep",
            WakerState::Unknown => "unknown",
        },
        beefy_data: if trusted { "live" } else if snap.is_some() { "stale" } else { "none" },
        watching,
        downloads: snap.map(|s| s.downloads.clone()),
        downloads_as_of: snap.filter(|_| !trusted).map(|s| s.at),
        listening: local.listening.map(|sessions| Listening { sessions }),
        audiobook_downloads,
        polled_at: polled.at,
        gate_failed: polled.gate_failed && waker == WakerState::Up,
    }
}

/// Last snapshot from a previous run; anything unreadable, of another version or with unknown categories is ignored.
pub fn load(path: &Path) -> Option<Snapshot> {
    let raw = std::fs::read(path).ok()?;
    let s: Snapshot = serde_json::from_slice(&raw).ok()?;
    (s.v == SNAPSHOT_VERSION).then_some(s)
}

/// Atomic write: temp file in the same directory, then rename.
pub fn save(path: &Path, snap: &Snapshot) -> std::io::Result<()> {
    let tmp = path.with_extension("json.tmp");
    let body = serde_json::to_vec(snap).map_err(std::io::Error::other)?;
    std::fs::write(&tmp, body)?;
    std::fs::rename(&tmp, path)
}

#[cfg(test)]
pub mod tests {
    use super::*;

    pub fn sample(at: i64) -> Snapshot {
        Snapshot {
            v: 1,
            at,
            streams: vec![Stream { kind: Kind::Episode, quality: Some(Quality::Fhd1080Sdr), mode: Mode::DirectPlay, paused: false, n: 1 }],
            downloads: vec![Download { state: DlState::Downloading, kind: Kind::Movie, quality: Some(Quality::Uhd4kHdr), items: 1, seasons: 0, episodes: 0 }],
        }
    }

    const NOW: i64 = 1_794_430_000;

    #[test]
    fn view_fresh_snapshot_and_waker_up_shows_streams() {
        let s = sample(NOW - 30);
        let v = view(NOW, Some(&s), WakerState::Up, &Local::default(), Polled::default());
        assert_eq!(v.beefy, "up");
        assert_eq!(v.beefy_data, "live");
        assert_eq!(v.watching, Some(s.streams.clone()));
        assert_eq!(v.downloads, Some(s.downloads.clone()));
        assert_eq!(v.downloads_as_of, None);
    }

    #[test]
    fn view_snapshot_older_than_90s_shows_nobody_watching_and_downloads_as_of() {
        let s = sample(NOW - 600);
        let v = view(NOW, Some(&s), WakerState::Down, &Local::default(), Polled::default());
        assert_eq!(v.beefy, "asleep");
        assert_eq!(v.beefy_data, "stale");
        assert_eq!(v.watching, Some(vec![]));
        assert_eq!(v.downloads, Some(s.downloads.clone()));
        assert_eq!(v.downloads_as_of, Some(NOW - 600));
        let v = view(NOW, Some(&sample(NOW - 90)), WakerState::Up, &Local::default(), Polled::default());
        assert_eq!(v.beefy_data, "stale");
        assert_eq!(v.watching, None, "awake but no fresh data = unavailable, never old streams");
        assert_eq!(v.downloads_as_of, Some(NOW - 90));
    }

    #[test]
    fn view_waker_down_ignores_fresh_snapshot_streams() {
        let s = sample(NOW - 5);
        let v = view(NOW, Some(&s), WakerState::Down, &Local::default(), Polled::default());
        assert_eq!(v.beefy, "asleep");
        assert_eq!(v.watching, Some(vec![]));
        assert_eq!(v.downloads_as_of, Some(NOW - 5));
    }

    #[test]
    fn view_waker_unknown_never_trusts_the_snapshot() {
        let fresh = sample(NOW - 10);
        let v = view(NOW, Some(&fresh), WakerState::Unknown, &Local::default(), Polled::default());
        assert_eq!(v.beefy, "unknown");
        assert_eq!(v.beefy_data, "stale", "only a fresh snapshot with the Waker saying up is live");
        assert_eq!(v.watching, None, "unknown = unavailable, even with a fresh snapshot");
        assert_eq!(v.downloads, Some(fresh.downloads.clone()));
        assert_eq!(v.downloads_as_of, Some(NOW - 10));
        let old = sample(NOW - 200);
        let v = view(NOW, Some(&old), WakerState::Unknown, &Local::default(), Polled::default());
        assert_eq!(v.watching, None);
        assert_eq!(v.downloads_as_of, Some(NOW - 200));
    }

    #[test]
    fn view_without_any_snapshot_has_no_beefy_data() {
        let v = view(NOW, None, WakerState::Up, &Local::default(), Polled::default());
        assert_eq!((v.beefy_data, v.watching, v.downloads, v.downloads_as_of), ("none", None, None, None));
        let v = view(NOW, None, WakerState::Down, &Local::default(), Polled::default());
        assert_eq!(v.watching, Some(vec![]));
    }

    #[test]
    fn view_local_figures_or_unavailable() {
        let l = Local { listening: Some(2), abr_downloading: Some(1), abr_queued: Some(3) };
        let v = view(NOW, None, WakerState::Down, &l, Polled::default());
        assert_eq!(v.listening, Some(Listening { sessions: 2 }));
        assert_eq!(v.audiobook_downloads, Some(AudiobookDownloads { downloading: 1, queued: 3 }));
        let v = view(NOW, None, WakerState::Down, &Local::default(), Polled::default());
        assert_eq!((v.listening, v.audiobook_downloads), (None, None));
    }

    #[test]
    fn view_reports_the_last_poll_and_a_failed_gate_only_while_up() {
        let failed = Polled { at: Some(NOW - 5), gate_failed: true };
        let v = view(NOW, None, WakerState::Up, &Local::default(), failed);
        assert_eq!((v.polled_at, v.gate_failed), (Some(NOW - 5), true));
        assert!(!view(NOW, None, WakerState::Down, &Local::default(), failed).gate_failed, "asleep: the gate is not asked");
        assert!(!view(NOW, None, WakerState::Unknown, &Local::default(), failed).gate_failed);
        let v = view(NOW, None, WakerState::Up, &Local::default(), Polled::default());
        assert_eq!((v.polled_at, v.gate_failed), (None, false));
        let j = serde_json::to_string(&view(NOW, None, WakerState::Up, &Local::default(), failed)).unwrap();
        assert!(j.contains(r#""polled_at":1794429995,"gate_failed":true"#), "{j}");
    }

    #[test]
    fn category_strings_are_exact() {
        let j = serde_json::to_string(&sample(1)).unwrap();
        assert!(j.contains(r#""kind":"Episode","quality":"1080p SDR","mode":"direct play""#), "{j}");
        assert!(j.contains(r#""state":"downloading","kind":"Movie","quality":"4K HDR""#), "{j}");
        for (m, s) in [(Mode::DirectStream, "direct stream"), (Mode::Transcode, "transcode"), (Mode::TranscodeAudio, "transcode (audio)")] {
            assert_eq!(serde_json::to_string(&m).unwrap(), format!("\"{s}\""));
            assert_eq!(m.label(), s);
        }
        for (d, s) in [(DlState::WaitingNight, "waiting for night"), (DlState::WaitingRelease, "waiting for release"), (DlState::Importing, "importing"), (DlState::Problem, "problem")] {
            assert_eq!(serde_json::to_string(&d).unwrap(), format!("\"{s}\""));
            assert_eq!(d.label(), s);
        }
    }

    #[test]
    fn quality_buckets() {
        assert_eq!(Quality::from_frame(2160, 3840, true), Some(Quality::Uhd4kHdr));
        assert_eq!(Quality::from_frame(1600, 3840, false), Some(Quality::Uhd4kSdr), "letterboxed 4K");
        assert_eq!(Quality::from_frame(1080, 1920, true), Some(Quality::Fhd1080Hdr));
        assert_eq!(Quality::from_frame(800, 1920, false), Some(Quality::Fhd1080Sdr), "letterboxed 1080p");
        assert_eq!(Quality::from_frame(720, 1280, true), Some(Quality::Hd720), "720p has no HDR split");
        assert_eq!(Quality::from_frame(576, 720, false), Some(Quality::Sd));
        assert_eq!(Quality::from_frame(0, 0, false), None);
    }

    #[test]
    fn persisted_snapshot_round_trips_and_rejects_unknown() {
        let dir = std::env::temp_dir().join(format!("activity-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("last.json");
        let s = sample(NOW);
        save(&p, &s).unwrap();
        assert_eq!(load(&p), Some(s));
        std::fs::write(&p, br#"{"v":2,"at":1,"streams":[],"downloads":[]}"#).unwrap();
        assert_eq!(load(&p), None);
        std::fs::write(&p, br#"{"v":1,"at":1,"streams":[{"kind":"Cartoon","quality":null,"mode":"direct play","paused":false,"n":1}],"downloads":[]}"#).unwrap();
        assert_eq!(load(&p), None);
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
