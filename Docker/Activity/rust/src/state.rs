//! Category values, the anonymous snapshot of beefy, the staleness rule and the view the page reads.

use std::path::Path;

use serde::{Deserialize, Serialize};

/// beefy data counts only while the last successful poll is younger than this.
pub const STALE_AFTER: i64 = 90;
/// After the Waker turns up, failures are not reported for this long: Jellyfin and the arrs start after sshd.
pub const WARM_UP: i64 = 90;
pub const SNAPSHOT_VERSION: u32 = 2;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub enum Kind {
    Movie,
    Episode,
    Anime,
    Audiobook,
    Music,
    #[serde(rename = "Live TV")]
    LiveTv,
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
    /// waiting to start: the client's queue, or a delay profile holding the release back
    #[serde(rename = "queued")]
    Queued,
    /// the client reports a warning (stalled, no connections) or is unavailable
    #[serde(rename = "stalled")]
    Stalled,
    /// paused in the client, not by the night rules
    #[serde(rename = "paused")]
    Paused,
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
            Kind::Music => "Music",
            Kind::LiveTv => "Live TV",
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
            DlState::Queued => "queued",
            DlState::Stalled => "stalled",
            DlState::Paused => "paused",
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

/// The Jellyfin side of one successful poll of beefy, already aggregated: categories and counts only.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StreamsPart {
    pub at: i64,
    pub streams: Vec<Stream>,
    /// the Sonarr series list was not available: anime counts as Episode
    #[serde(default)]
    pub series_unavailable: bool,
}

/// What a downloads part may be missing: the series list (anime, series counts), the night list (night-held items look paused), or queue records beyond the page.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Gaps {
    pub series_unavailable: bool,
    pub night_unavailable: bool,
    pub truncated: bool,
}

/// The queue side of one successful poll of beefy; kept on disk for "as of" after a restart.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DownloadsPart {
    pub at: i64,
    pub list: Vec<Download>,
    #[serde(default)]
    pub gaps: Gaps,
    /// night-waiting.json `low_tariff`: the night window (22:00–06:00, Sundays all day) is open
    #[serde(default)]
    pub night_open: Option<bool>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Saved {
    v: u32,
    downloads: DownloadsPart,
}

/// last.json before the parts were split: one `at` for streams and downloads.
#[derive(Deserialize)]
struct SavedV1 {
    v: u32,
    at: i64,
    downloads: Vec<Download>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WakerState {
    Up,
    Down,
    /// a wake (or its recovery) is in progress: still off
    Waking,
    /// the last wake failed
    Broken,
    Unknown,
}

/// qBittorrent category abr torrents by state.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize)]
pub struct Abr {
    pub downloading: u32,
    pub queued: u32,
    pub paused: u32,
    pub problem: u32,
}

/// fastpi-local audiobook figures; None = source unavailable.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Local {
    pub listening: Option<u32>,
    pub abr: Option<Abr>,
}

#[derive(Debug, PartialEq, Serialize)]
pub struct Listening {
    pub sessions: u32,
}

#[derive(Debug, PartialEq, Serialize)]
pub struct View {
    pub now: i64,
    /// "up" | "asleep" | "waking" | "broken" (the last wake failed) | "unknown" (Waker /status)
    pub beefy: &'static str,
    /// "live" (fresh streams, Waker up) | "stale" (last known only) | "none" (never polled)
    pub beefy_data: &'static str,
    /// None = unavailable (awake without fresh data, wake failed, or Waker state unknown); empty while asleep or waking = nobody watching
    pub watching: Option<Vec<Stream>>,
    /// None = never polled
    pub downloads: Option<Vec<Download>>,
    /// set when `downloads` is the last known state, not live
    pub downloads_as_of: Option<i64>,
    /// what the downloads may be missing (None = no downloads)
    pub downloads_gaps: Option<Gaps>,
    /// the night window was open at the last downloads poll (None = unknown)
    pub night_open: Option<bool>,
    /// the live streams were grouped without the Sonarr series list (anime shows as Episode)
    pub streams_series_unavailable: bool,
    pub listening: Option<Listening>,
    pub audiobook_downloads: Option<Abr>,
    /// when the last poll finished (None = no poll since the start)
    pub polled_at: Option<i64>,
    /// the Waker says up (past the warm-up) but the last poll got no sessions / no queues from the gate
    pub streams_failed: bool,
    pub downloads_failed: bool,
    /// beefy woke within the last WARM_UP seconds and has no live data yet: its services are still starting
    pub beefy_starting: bool,
}

/// What the last poll left behind besides the data.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Polled {
    pub at: Option<i64>,
    pub streams_failed: bool,
    pub downloads_failed: bool,
    /// when the Waker turned up after an observed sleep or wake (None = up since before the service saw it)
    pub up_since: Option<i64>,
}

/// Fresh = taken within STALE_AFTER and not in the future (a stepped clock never makes old data live).
fn fresh(now: i64, at: i64) -> bool {
    (0..STALE_AFTER).contains(&(now - at))
}

pub fn view(now: i64, streams: Option<&StreamsPart>, downloads: Option<&DownloadsPart>, waker: WakerState, local: &Local, polled: Polled) -> View {
    let up = waker == WakerState::Up;
    let live = up && streams.is_some_and(|s| fresh(now, s.at));
    let downloads_live = up && downloads.is_some_and(|d| fresh(now, d.at));
    let warming = up && polled.up_since.is_some_and(|t| (0..WARM_UP).contains(&(now - t)));
    let watching = match (live, waker) {
        (true, _) => streams.map(|s| s.streams.clone()),
        (false, WakerState::Down | WakerState::Waking) => Some(Vec::new()),
        _ => None,
    };
    View {
        now,
        beefy: match waker {
            WakerState::Up => "up",
            WakerState::Down => "asleep",
            WakerState::Waking => "waking",
            WakerState::Broken => "broken",
            WakerState::Unknown => "unknown",
        },
        beefy_data: if live { "live" } else if streams.is_some() || downloads.is_some() { "stale" } else { "none" },
        watching,
        downloads: downloads.map(|d| d.list.clone()),
        downloads_as_of: downloads.filter(|_| !downloads_live).map(|d| d.at),
        downloads_gaps: downloads.map(|d| d.gaps),
        night_open: downloads.and_then(|d| d.night_open),
        streams_series_unavailable: live && streams.is_some_and(|s| s.series_unavailable),
        listening: local.listening.map(|sessions| Listening { sessions }),
        audiobook_downloads: local.abr,
        polled_at: polled.at,
        streams_failed: up && !warming && polled.streams_failed,
        downloads_failed: up && !warming && polled.downloads_failed,
        beefy_starting: warming && !live,
    }
}

/// Last downloads from a previous run; anything unreadable, of another version or with unknown categories is ignored.
pub fn load(path: &Path) -> Option<DownloadsPart> {
    let raw = std::fs::read(path).ok()?;
    if let Ok(s) = serde_json::from_slice::<Saved>(&raw) {
        return (s.v == SNAPSHOT_VERSION).then_some(s.downloads);
    }
    let old: SavedV1 = serde_json::from_slice(&raw).ok()?;
    (old.v == 1).then_some(DownloadsPart { at: old.at, list: old.downloads, gaps: Gaps::default(), night_open: None })
}

/// Atomic write: temp file in the same directory, then rename.
pub fn save(path: &Path, downloads: &DownloadsPart) -> std::io::Result<()> {
    let tmp = path.with_extension("json.tmp");
    let body = serde_json::to_vec(&Saved { v: SNAPSHOT_VERSION, downloads: downloads.clone() }).map_err(std::io::Error::other)?;
    std::fs::write(&tmp, body)?;
    std::fs::rename(&tmp, path)
}

#[cfg(test)]
pub mod tests {
    use super::*;

    pub fn streams_part(at: i64) -> StreamsPart {
        StreamsPart { at, series_unavailable: false, streams: vec![Stream { kind: Kind::Episode, quality: Some(Quality::Fhd1080Sdr), mode: Mode::DirectPlay, paused: false, n: 1 }] }
    }
    pub fn downloads_part(at: i64) -> DownloadsPart {
        DownloadsPart { at, gaps: Gaps::default(), night_open: None, list: vec![Download { state: DlState::Downloading, kind: Kind::Movie, quality: Some(Quality::Uhd4kHdr), items: 1, seasons: 0, episodes: 0 }] }
    }

    const NOW: i64 = 1_794_430_000;

    fn v(s: Option<i64>, d: Option<i64>, w: WakerState, p: Polled) -> View {
        view(NOW, s.map(streams_part).as_ref(), d.map(downloads_part).as_ref(), w, &Local::default(), p)
    }

    #[test]
    fn view_fresh_parts_and_waker_up_shows_streams() {
        let x = v(Some(NOW - 30), Some(NOW - 30), WakerState::Up, Polled::default());
        assert_eq!(x.beefy, "up");
        assert_eq!(x.beefy_data, "live");
        assert_eq!(x.watching, Some(streams_part(0).streams));
        assert_eq!(x.downloads, Some(downloads_part(0).list));
        assert_eq!(x.downloads_as_of, None);
    }

    #[test]
    fn a_failed_downloads_part_keeps_the_streams_live() {
        let p = Polled { at: Some(NOW - 5), downloads_failed: true, ..Polled::default() };
        let x = v(Some(NOW - 5), Some(NOW - 900), WakerState::Up, p);
        assert_eq!(x.beefy_data, "live");
        assert_eq!(x.watching, Some(streams_part(0).streams), "the streams do not depend on the queues");
        assert_eq!(x.downloads_as_of, Some(NOW - 900), "the downloads stay as last known");
        assert!(x.downloads_failed && !x.streams_failed);
        let p = Polled { at: Some(NOW - 5), streams_failed: true, ..Polled::default() };
        let x = v(Some(NOW - 900), Some(NOW - 5), WakerState::Up, p);
        assert_eq!(x.watching, None, "no fresh streams while awake = unavailable");
        assert_eq!(x.downloads_as_of, None, "the downloads are live");
        assert!(x.streams_failed && !x.downloads_failed);
    }

    #[test]
    fn view_old_parts_show_nobody_watching_and_downloads_as_of() {
        let x = v(Some(NOW - 600), Some(NOW - 600), WakerState::Down, Polled::default());
        assert_eq!(x.beefy, "asleep");
        assert_eq!(x.beefy_data, "stale");
        assert_eq!(x.watching, Some(vec![]));
        assert_eq!(x.downloads_as_of, Some(NOW - 600));
        let x = v(Some(NOW - 90), Some(NOW - 90), WakerState::Up, Polled::default());
        assert_eq!(x.beefy_data, "stale");
        assert_eq!(x.watching, None, "awake but no fresh data = unavailable, never old streams");
        assert_eq!(x.downloads_as_of, Some(NOW - 90));
    }

    #[test]
    fn a_future_dated_part_is_stale_not_live() {
        let x = v(Some(NOW + 600), Some(NOW + 600), WakerState::Up, Polled::default());
        assert_eq!(x.beefy_data, "stale", "clock skew: a snapshot from the future is never fresh");
        assert_eq!(x.watching, None);
        assert_eq!(x.downloads_as_of, Some(NOW + 600));
    }

    #[test]
    fn view_waker_down_ignores_fresh_streams() {
        let x = v(Some(NOW - 5), Some(NOW - 5), WakerState::Down, Polled::default());
        assert_eq!(x.watching, Some(vec![]));
        assert_eq!(x.downloads_as_of, Some(NOW - 5));
    }

    #[test]
    fn waking_and_broken_are_not_asleep() {
        let x = v(None, None, WakerState::Waking, Polled::default());
        assert_eq!(x.beefy, "waking");
        assert_eq!(x.watching, Some(vec![]), "still off while it wakes: nobody can be watching yet");
        let x = v(Some(NOW - 5), None, WakerState::Broken, Polled::default());
        assert_eq!(x.beefy, "broken");
        assert_eq!(x.watching, None, "a failed wake: state unknown");
    }

    #[test]
    fn view_waker_unknown_never_trusts_the_parts() {
        let x = v(Some(NOW - 10), Some(NOW - 10), WakerState::Unknown, Polled::default());
        assert_eq!(x.beefy, "unknown");
        assert_eq!(x.beefy_data, "stale", "only fresh streams with the Waker saying up are live");
        assert_eq!(x.watching, None);
        assert_eq!(x.downloads_as_of, Some(NOW - 10));
    }

    #[test]
    fn view_without_any_part_has_no_beefy_data() {
        let x = v(None, None, WakerState::Up, Polled::default());
        assert_eq!((x.beefy_data, x.watching, x.downloads, x.downloads_as_of), ("none", None, None, None));
        assert_eq!(v(None, None, WakerState::Down, Polled::default()).watching, Some(vec![]));
    }

    #[test]
    fn view_local_figures_or_unavailable() {
        let abr = Abr { downloading: 1, queued: 3, paused: 1, problem: 0 };
        let l = Local { listening: Some(2), abr: Some(abr) };
        let x = view(NOW, None, None, WakerState::Down, &l, Polled::default());
        assert_eq!(x.listening, Some(Listening { sessions: 2 }));
        assert_eq!(x.audiobook_downloads, Some(abr));
        let x = view(NOW, None, None, WakerState::Down, &Local::default(), Polled::default());
        assert_eq!((x.listening, x.audiobook_downloads), (None, None));
    }

    #[test]
    fn gaps_in_the_downloads_are_shown() {
        let mut d = downloads_part(NOW - 5);
        d.gaps = Gaps { series_unavailable: true, night_unavailable: false, truncated: true };
        let x = view(NOW, None, Some(&d), WakerState::Up, &Local::default(), Polled::default());
        assert_eq!(x.downloads_gaps, Some(Gaps { series_unavailable: true, night_unavailable: false, truncated: true }));
        let j = serde_json::to_string(&x).unwrap();
        assert!(j.contains(r#""downloads_gaps":{"series_unavailable":true,"night_unavailable":false,"truncated":true}"#), "{j}");
        let x = view(NOW, Some(&StreamsPart { series_unavailable: true, ..streams_part(NOW - 5) }), None, WakerState::Up, &Local::default(), Polled::default());
        assert!(x.streams_series_unavailable, "anime cannot be told apart without the series list");
    }

    #[test]
    fn failures_are_reported_only_while_up_and_after_the_warm_up() {
        let failed = Polled { at: Some(NOW - 5), streams_failed: true, downloads_failed: true, up_since: None };
        let x = v(None, None, WakerState::Up, failed);
        assert_eq!((x.polled_at, x.streams_failed, x.downloads_failed, x.beefy_starting), (Some(NOW - 5), true, true, false));
        assert!(!v(None, None, WakerState::Down, failed).streams_failed, "asleep: the gate is not asked");
        assert!(!v(None, None, WakerState::Unknown, failed).downloads_failed);
        let woke = Polled { up_since: Some(NOW - 20), ..failed };
        let x = v(None, None, WakerState::Up, woke);
        assert_eq!((x.streams_failed, x.downloads_failed, x.beefy_starting), (false, false, true), "just woke: services still starting, no false alarm");
        let x = v(Some(NOW - 3), Some(NOW - 3), WakerState::Up, Polled { streams_failed: false, downloads_failed: false, ..woke });
        assert!(!x.beefy_starting, "live data: no longer starting");
        let x = v(None, None, WakerState::Up, Polled { up_since: Some(NOW - WARM_UP), ..failed });
        assert!(x.streams_failed && !x.beefy_starting, "after the warm-up a failure counts");
        let j = serde_json::to_string(&v(None, None, WakerState::Up, failed)).unwrap();
        assert!(j.contains(r#""polled_at":1794429995,"streams_failed":true,"downloads_failed":true,"beefy_starting":false"#), "{j}");
    }

    #[test]
    fn category_strings_are_exact() {
        let j = serde_json::to_string(&streams_part(1)).unwrap() + &serde_json::to_string(&downloads_part(1)).unwrap();
        assert!(j.contains(r#""kind":"Episode","quality":"1080p SDR","mode":"direct play""#), "{j}");
        assert!(j.contains(r#""state":"downloading","kind":"Movie","quality":"4K HDR""#), "{j}");
        for (m, s) in [(Mode::DirectStream, "direct stream"), (Mode::Transcode, "transcode"), (Mode::TranscodeAudio, "transcode (audio)")] {
            assert_eq!(serde_json::to_string(&m).unwrap(), format!("\"{s}\""));
            assert_eq!(m.label(), s);
        }
        for (d, s) in [
            (DlState::WaitingNight, "waiting for night"),
            (DlState::WaitingRelease, "waiting for release"),
            (DlState::Importing, "importing"),
            (DlState::Queued, "queued"),
            (DlState::Stalled, "stalled"),
            (DlState::Paused, "paused"),
            (DlState::Problem, "problem"),
        ] {
            assert_eq!(serde_json::to_string(&d).unwrap(), format!("\"{s}\""));
            assert_eq!(d.label(), s);
        }
    }

    #[test]
    fn kind_strings_are_exact() {
        for (k, s) in [(Kind::Movie, "Movie"), (Kind::Episode, "Episode"), (Kind::Anime, "Anime"), (Kind::Audiobook, "Audiobook"), (Kind::Music, "Music"), (Kind::LiveTv, "Live TV"), (Kind::Other, "Other")] {
            assert_eq!(serde_json::to_string(&k).unwrap(), format!("\"{s}\""));
            assert_eq!(k.label(), s);
        }
    }

    #[test]
    fn the_night_window_state_is_shown_with_the_downloads() {
        let d = DownloadsPart { night_open: Some(true), ..downloads_part(NOW - 5) };
        assert_eq!(view(NOW, None, Some(&d), WakerState::Up, &Local::default(), Polled::default()).night_open, Some(true));
        assert_eq!(view(NOW, None, None, WakerState::Up, &Local::default(), Polled::default()).night_open, None);
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

    fn tmp(name: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!("activity-test-{name}-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        dir.join("last.json")
    }

    #[test]
    fn persisted_downloads_round_trip_and_reject_unknown() {
        let p = tmp("rt");
        let d = downloads_part(NOW);
        save(&p, &d).unwrap();
        assert_eq!(load(&p), Some(d));
        std::fs::write(&p, br#"{"v":3,"downloads":{"at":1,"list":[]}}"#).unwrap();
        assert_eq!(load(&p), None);
        std::fs::write(&p, br#"{"v":2,"downloads":{"at":1,"list":[{"state":"exploded","kind":"Movie","quality":null,"items":1,"seasons":0,"episodes":0}]}}"#).unwrap();
        assert_eq!(load(&p), None);
        std::fs::remove_dir_all(p.parent().unwrap()).unwrap();
    }

    #[test]
    fn a_version_1_file_keeps_its_downloads() {
        let p = tmp("v1");
        std::fs::write(&p, br#"{"v":1,"at":7,"streams":[{"kind":"Movie","quality":null,"mode":"direct play","paused":false,"n":1}],"downloads":[{"state":"downloading","kind":"Movie","quality":"4K HDR","items":1,"seasons":0,"episodes":0}]}"#).unwrap();
        assert_eq!(load(&p), Some(downloads_part(7)));
        std::fs::remove_dir_all(p.parent().unwrap()).unwrap();
    }
}
