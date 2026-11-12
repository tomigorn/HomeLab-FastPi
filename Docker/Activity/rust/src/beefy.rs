//! beefy figures through the read-only activity-gate: the gate paths (a contract with the gate config on beefy),
//! typed parsers that keep only the fields the categories need, and the grouping into anonymous counts.

use std::collections::{BTreeMap, HashMap, HashSet};

use serde::Deserialize;

use crate::state::{DlState, Download, Kind, Mode, Quality, Stream};

/// Paths on the gate (`GATE_URL`); the gate on beefy allow-lists exactly these GET paths and injects the API keys.
pub const PATH_SESSIONS: &str = "/jellyfin/Sessions?ActiveWithinSeconds=60";
pub const PATH_RADARR_QUEUE: &str = "/radarr/api/v3/queue?pageSize=200&includeMovie=true";
pub const PATH_SONARR_QUEUE: &str = "/sonarr/api/v3/queue?pageSize=500&includeSeries=true&includeEpisode=true";
pub const PATH_SONARR_SERIES: &str = "/sonarr/api/v3/series";
pub const PATH_REQUEST_STATE: &str = "/seerr/request-state.json";
pub const PATH_NIGHT_WAITING: &str = "/seerr/night-waiting.json";

#[cfg_attr(not(test), allow(dead_code))]
pub const GATE_PATHS: [&str; 6] =
    [PATH_SESSIONS, PATH_RADARR_QUEUE, PATH_SONARR_QUEUE, PATH_SONARR_SERIES, PATH_REQUEST_STATE, PATH_NIGHT_WAITING];

// ---------- Jellyfin ----------

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "PascalCase")]
pub struct Session {
    now_playing_item: Option<Item>,
    play_state: Option<PlayState>,
    transcoding_info: Option<TranscodingInfo>,
}

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "PascalCase")]
struct Item {
    #[serde(rename = "Type")]
    kind: Option<String>,
    series_name: Option<String>,
    path: Option<String>,
    media_streams: Option<Vec<MediaStream>>,
}

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "PascalCase")]
struct MediaStream {
    #[serde(rename = "Type")]
    kind: Option<String>,
    height: Option<u32>,
    width: Option<u32>,
    video_range: Option<String>,
    video_range_type: Option<String>,
}

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "PascalCase")]
struct PlayState {
    play_method: Option<String>,
    is_paused: Option<bool>,
}

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "PascalCase")]
struct TranscodingInfo {
    is_video_direct: Option<bool>,
}

/// The Sonarr series list boiled down to what the categories need, kept between polls (refreshed every SERIES_TTL or on an unknown series):
/// anime series as keyed hashes of their lower-case title and folder name (no title is kept), series ids, and per tmdb id anime or not plus the missing (seasons, episodes).
#[derive(Debug, Default)]
pub struct SeriesIndex {
    pub at: i64,
    built: bool,
    hasher: std::collections::hash_map::RandomState,
    anime_names: HashSet<u64>,
    anime_folders: HashSet<u64>,
    ids: HashSet<i64>,
    by_tmdb: HashMap<i64, (bool, (u32, u32))>,
    /// ids that were unknown when this index was built: not looked up again before SERIES_TTL
    tried: HashSet<String>,
}

/// The series list is read again after this many seconds.
pub const SERIES_TTL: i64 = 1800;

impl SeriesIndex {
    pub fn build(series: &[Series], at: i64, sonarr: &Queue, rs: &RequestState) -> SeriesIndex {
        let mut idx = SeriesIndex { at, built: true, ..SeriesIndex::default() };
        for s in series {
            if let Some(id) = s.id {
                idx.ids.insert(id);
            }
            if let Some(t) = s.tmdb_id {
                idx.by_tmdb.insert(t, (s.is_anime(), s.missing()));
            }
            if !s.is_anime() {
                continue;
            }
            if let Some(t) = &s.title {
                let h = idx.hash(t);
                idx.anime_names.insert(h);
            }
            if let Some(f) = s.path.as_deref().and_then(|p| p.trim_end_matches('/').rsplit('/').next()).filter(|f| !f.is_empty()) {
                let h = idx.hash(f);
                idx.anime_folders.insert(h);
            }
        }
        idx.tried = idx.unknown(sonarr, rs);
        idx
    }

    fn hash(&self, s: &str) -> u64 {
        use std::hash::BuildHasher;
        self.hasher.hash_one(s.to_lowercase())
    }

    /// Sonarr queue series ids and requested tv tmdb ids this index does not know.
    fn unknown(&self, sonarr: &Queue, rs: &RequestState) -> HashSet<String> {
        let queue = sonarr.records.iter().flatten().filter_map(|r| r.series_id).filter(|id| *id > 0 && !self.ids.contains(id)).map(|id| format!("s{id}"));
        let requested = rs.tv_tmdb_ids().filter(|t| !self.by_tmdb.contains_key(t)).map(|t| format!("t{t}"));
        queue.chain(requested).collect()
    }

    /// Never built, SERIES_TTL old (or from the future), or an id appeared that was not looked up yet.
    pub fn needs_refresh(&self, now: i64, sonarr: &Queue, rs: &RequestState) -> bool {
        !self.built || !(0..SERIES_TTL).contains(&(now - self.at)) || self.unknown(sonarr, rs).iter().any(|u| !self.tried.contains(u))
    }

    fn is_anime_item(&self, item: &Item) -> bool {
        if item.series_name.as_deref().is_some_and(|n| self.anime_names.contains(&self.hash(n))) {
            return true;
        }
        item.path.as_deref().is_some_and(|p| p.split('/').filter(|c| !c.is_empty()).any(|c| self.anime_folders.contains(&self.hash(c))))
    }

    fn tmdb(&self, tmdb: i64) -> Option<(bool, (u32, u32))> {
        self.by_tmdb.get(&tmdb).copied()
    }
}

fn is_hdr(range: Option<&str>, range_type: Option<&str>) -> bool {
    let t = range_type.unwrap_or("").to_ascii_uppercase();
    t.starts_with("HDR") || t.starts_with("DOVI") || t == "HLG" || range.unwrap_or("").eq_ignore_ascii_case("HDR")
}

fn stream_of(s: &Session, anime: &SeriesIndex) -> Option<Stream> {
    let item = s.now_playing_item.as_ref()?;
    let video = item.media_streams.as_deref().unwrap_or_default().iter().find(|m| m.kind.as_deref() == Some("Video"));
    let kind = match (item.kind.as_deref(), video) {
        (_, None) => Kind::Other,
        (Some("Movie"), _) => Kind::Movie,
        (Some("Episode"), _) if anime.is_anime_item(item) => Kind::Anime,
        (Some("Episode"), _) => Kind::Episode,
        _ => Kind::Other,
    };
    let quality = video.and_then(|v| {
        Quality::from_frame(v.height.unwrap_or(0), v.width.unwrap_or(0), is_hdr(v.video_range.as_deref(), v.video_range_type.as_deref()))
    });
    let ps = s.play_state.as_ref();
    let mode = match ps.and_then(|p| p.play_method.as_deref()) {
        Some("DirectStream") => Mode::DirectStream,
        Some("Transcode") if s.transcoding_info.as_ref().and_then(|t| t.is_video_direct) == Some(true) => Mode::TranscodeAudio,
        Some("Transcode") => Mode::Transcode,
        _ => Mode::DirectPlay,
    };
    Some(Stream { kind, quality, mode, paused: ps.and_then(|p| p.is_paused).unwrap_or(false), n: 1 })
}

/// Playing sessions grouped by kind × quality × mode × paused; sessions without a playing item are not streams.
pub fn streams(sessions: &[Session], anime: &SeriesIndex) -> Vec<Stream> {
    let mut groups: BTreeMap<(Kind, Option<Quality>, Mode, bool), u32> = BTreeMap::new();
    for s in sessions.iter().filter_map(|s| stream_of(s, anime)) {
        *groups.entry((s.kind, s.quality, s.mode, s.paused)).or_default() += 1;
    }
    groups.into_iter().map(|((kind, quality, mode, paused), n)| Stream { kind, quality, mode, paused, n }).collect()
}

pub fn wants_series(sessions: &[Session]) -> bool {
    sessions.iter().any(|s| s.now_playing_item.as_ref().is_some_and(|i| i.kind.as_deref() == Some("Episode")))
}

// ---------- Radarr / Sonarr ----------

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "camelCase")]
pub struct Queue {
    total_records: Option<u32>,
    records: Option<Vec<QueueRecord>>,
}

impl Queue {
    /// (records read, records in the queue) when the page holds fewer than the queue reports.
    pub fn truncated(&self) -> Option<(usize, u32)> {
        let n = self.records.as_ref().map_or(0, Vec::len);
        self.total_records.filter(|&t| t as usize > n).map(|t| (n, t))
    }
}

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "camelCase")]
struct QueueRecord {
    movie_id: Option<i64>,
    series_id: Option<i64>,
    season_number: Option<i64>,
    status: Option<String>,
    tracked_download_state: Option<String>,
    tracked_download_status: Option<String>,
    download_id: Option<String>,
    quality: Option<QualityModel>,
    custom_formats: Option<Vec<CustomFormat>>,
    series: Option<SeriesRef>,
    episode: Option<EpisodeRef>,
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct QualityModel {
    quality: Option<QualityDef>,
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct QualityDef {
    resolution: Option<u32>,
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct CustomFormat {
    name: Option<String>,
}

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "camelCase")]
struct SeriesRef {
    series_type: Option<String>,
}

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "camelCase")]
struct EpisodeRef {
    season_number: Option<i64>,
}

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "camelCase")]
pub struct Series {
    id: Option<i64>,
    tmdb_id: Option<i64>,
    title: Option<String>,
    series_type: Option<String>,
    path: Option<String>,
    seasons: Option<Vec<Season>>,
}

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "camelCase")]
struct Season {
    season_number: i64,
    monitored: bool,
    statistics: Option<SeasonStats>,
}

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "camelCase")]
struct SeasonStats {
    episode_count: u32,
    episode_file_count: u32,
}

impl Series {
    fn is_anime(&self) -> bool {
        self.series_type.as_deref().is_some_and(|t| t.eq_ignore_ascii_case("anime"))
    }

    /// (seasons, episodes) still missing in the monitored seasons.
    fn missing(&self) -> (u32, u32) {
        let mut out = (0, 0);
        for s in self.seasons.as_deref().unwrap_or_default().iter().filter(|s| s.monitored && s.season_number > 0) {
            let st = s.statistics.as_ref();
            let left = st.map(|st| st.episode_count.saturating_sub(st.episode_file_count)).unwrap_or(0);
            if left > 0 {
                out.0 += 1;
                out.1 += left;
            }
        }
        out
    }
}

/// Seerr `request-state.json` (written on beefy by Movie-Downloads/scripts/night-downloads.py): ids only, keys `movie/<tmdb>` | `tv/<tmdb>`.
#[derive(Deserialize, Default, Clone)]
#[serde(default, rename_all = "camelCase")]
pub struct RequestState {
    can_wait: Option<Vec<String>>,
    unreleased: Option<HashMap<String, serde_json::Value>>,
    no_release: Option<HashMap<String, serde_json::Value>>,
    queue: Option<HashMap<String, serde_json::Value>>,
}

impl RequestState {
    fn keys(&self) -> impl Iterator<Item = &String> {
        self.can_wait.iter().flatten().chain(self.unreleased.iter().flat_map(|m| m.keys())).chain(self.no_release.iter().flat_map(|m| m.keys()))
    }

    pub fn has_tv(&self) -> bool {
        self.keys().any(|k| k.starts_with("tv/"))
    }

    fn tv_tmdb_ids(&self) -> impl Iterator<Item = i64> + '_ {
        self.keys().filter_map(|k| k.strip_prefix("tv/")?.parse().ok())
    }
}

/// Seerr `night-waiting.json`: download ids held for the night (qBittorrent hashes, SABnzbd nzo ids).
#[derive(Deserialize, Default)]
#[serde(default)]
pub struct NightWaiting {
    waiting: Option<Vec<String>>,
}

impl NightWaiting {
    pub fn ids(&self) -> HashSet<String> {
        self.waiting.iter().flatten().map(|s| s.to_lowercase()).collect()
    }
}

const PROBLEM_STATES: [&str; 3] = ["importBlocked", "failedPending", "failed"];
const IMPORT_STATES: [&str; 2] = ["importPending", "importing"];
const DONE_STATES: [&str; 2] = ["imported", "ignored"];

/// Which state a title with several queue records shows (night-downloads.py order, extended): problem > stalled > importing > downloading > queued > paused > held for the night.
fn rank(s: DlState) -> u8 {
    match s {
        DlState::Problem => 7,
        DlState::Stalled => 6,
        DlState::Importing => 5,
        DlState::Downloading => 4,
        DlState::Queued => 3,
        DlState::Paused => 2,
        DlState::WaitingNight => 1,
        DlState::WaitingRelease => 0,
    }
}

/// Radarr/Sonarr v3 `status` (from the download client) and `trackedDownloadState`/`trackedDownloadStatus` → state; None = done (imported, ignored), not shown.
fn record_state(r: &QueueRecord, night: &HashSet<String>) -> Option<DlState> {
    let tds = r.tracked_download_state.as_deref().unwrap_or("");
    let tstatus = r.tracked_download_status.as_deref().unwrap_or("");
    let status = r.status.as_deref().unwrap_or("").to_ascii_lowercase();
    let st = if DONE_STATES.contains(&tds) {
        return None;
    } else if PROBLEM_STATES.contains(&tds) || tstatus == "error" || status == "failed" {
        DlState::Problem
    } else if IMPORT_STATES.contains(&tds) || status == "completed" {
        DlState::Importing
    } else if status == "paused" {
        if r.download_id.as_deref().is_some_and(|id| night.contains(&id.to_lowercase())) { DlState::WaitingNight } else { DlState::Paused }
    } else if status == "queued" || status == "delay" {
        DlState::Queued
    } else if status == "warning" || status == "downloadclientunavailable" || tstatus == "warning" {
        DlState::Stalled
    } else {
        DlState::Downloading
    };
    Some(st)
}

fn record_quality(r: &QueueRecord) -> Option<Quality> {
    let res = r.quality.as_ref()?.quality.as_ref()?.resolution.unwrap_or(0);
    let hdr = r.custom_formats.iter().flatten().filter_map(|c| c.name.as_deref()).any(|n| {
        let n = n.to_ascii_uppercase();
        n.contains("HDR") || n.contains("DOLBY VISION") || n.contains("HLG") || n.split(|c: char| !c.is_ascii_alphanumeric()).any(|w| w == "DV" || w == "DOVI")
    });
    if res == 0 {
        return None;
    }
    Quality::from_frame(res, 0, hdr)
}

#[derive(Default)]
struct Bucket {
    items: HashSet<String>,
    seasons: HashSet<(String, i64)>,
    episodes: u32,
    extra_seasons: u32,
}

type Key = (DlState, Kind, Option<Quality>);

/// Queues, request state and series grouped into state × kind × quality with item, season and episode counts.
pub fn downloads(radarr: &Queue, sonarr: &Queue, rs: &RequestState, series: &SeriesIndex, night: &HashSet<String>) -> Vec<Download> {
    let mut buckets: BTreeMap<Key, Bucket> = BTreeMap::new();

    let mut movies: HashMap<i64, (DlState, Option<Quality>)> = HashMap::new();
    for r in radarr.records.iter().flatten() {
        let Some(id) = r.movie_id.filter(|&id| id > 0) else { continue };
        let Some(st) = record_state(r, night) else { continue };
        let q = record_quality(r);
        match movies.get(&id) {
            Some((old, _)) if rank(*old) >= rank(st) => {}
            _ => {
                movies.insert(id, (st, q));
            }
        }
    }
    for (id, (st, q)) in movies {
        buckets.entry((st, Kind::Movie, q)).or_default().items.insert(format!("m{id}"));
    }

    for r in sonarr.records.iter().flatten() {
        let Some(id) = r.series_id.filter(|&id| id > 0) else { continue };
        let Some(st) = record_state(r, night) else { continue };
        let anime = r.series.as_ref().and_then(|s| s.series_type.as_deref()).is_some_and(|t| t.eq_ignore_ascii_case("anime"));
        let b = buckets.entry((st, if anime { Kind::Anime } else { Kind::Episode }, record_quality(r))).or_default();
        b.items.insert(format!("s{id}"));
        if let Some(season) = r.episode.as_ref().and_then(|e| e.season_number).or(r.season_number) {
            b.seasons.insert((format!("s{id}"), season));
        }
        b.episodes += 1;
    }

    let in_queue: HashSet<&String> = rs.queue.iter().flat_map(|m| m.keys()).collect();
    let release: HashSet<&String> = rs.unreleased.iter().flat_map(|m| m.keys()).chain(rs.no_release.iter().flat_map(|m| m.keys())).collect();
    let mut add = |key: &String, state: DlState| {
        let (kind, show) = match key.split_once('/') {
            Some(("movie", _)) => (Kind::Movie, None),
            Some(("tv", id)) => {
                let s = id.parse::<i64>().ok().and_then(|t| series.tmdb(t));
                (if s.is_some_and(|(anime, _)| anime) { Kind::Anime } else { Kind::Episode }, s)
            }
            _ => return,
        };
        let b = buckets.entry((state, kind, None)).or_default();
        if b.items.insert(format!("r{key}")) && state == DlState::WaitingNight {
            if let Some((_, (seasons, episodes))) = show {
                b.extra_seasons += seasons;
                b.episodes += episodes;
            }
        }
    };
    for key in rs.can_wait.iter().flatten().filter(|k| !in_queue.contains(k) && !release.contains(k)) {
        add(key, DlState::WaitingNight);
    }
    for key in release.iter().filter(|k| !in_queue.contains(**k)) {
        add(key, DlState::WaitingRelease);
    }

    buckets
        .into_iter()
        .map(|((state, kind, quality), b)| Download {
            state,
            kind,
            quality,
            items: b.items.len() as u32,
            seasons: b.seasons.len() as u32 + b.extra_seasons,
            episodes: b.episodes,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    const SESSIONS: &str = include_str!("../fixtures/sessions.json");
    const RADARR: &str = include_str!("../fixtures/radarr-queue.json");
    const SONARR: &str = include_str!("../fixtures/sonarr-queue.json");
    const SERIES: &str = include_str!("../fixtures/sonarr-series.json");
    const REQUESTS: &str = include_str!("../fixtures/request-state.json");
    const NIGHT: &str = include_str!("../fixtures/night-waiting.json");

    fn sessions() -> Vec<Session> {
        serde_json::from_str(SESSIONS).unwrap()
    }
    fn series() -> Vec<Series> {
        serde_json::from_str(SERIES).unwrap()
    }
    fn index() -> SeriesIndex {
        SeriesIndex::build(&series(), 1000, &Queue::default(), &RequestState::default())
    }
    fn one(json: &str) -> Vec<Stream> {
        let s: Session = serde_json::from_str(json).unwrap();
        streams(&[s], &index())
    }
    fn st(kind: Kind, quality: Option<Quality>, mode: Mode, paused: bool, n: u32) -> Stream {
        Stream { kind, quality, mode, paused, n }
    }
    fn dl(state: DlState, kind: Kind, quality: Option<Quality>, items: u32, seasons: u32, episodes: u32) -> Download {
        Download { state, kind, quality, items, seasons, episodes }
    }
    fn all_downloads() -> Vec<Download> {
        downloads(
            &serde_json::from_str(RADARR).unwrap(),
            &serde_json::from_str(SONARR).unwrap(),
            &serde_json::from_str(REQUESTS).unwrap(),
            &index(),
            &serde_json::from_str::<NightWaiting>(NIGHT).unwrap().ids(),
        )
    }

    #[test]
    fn session_4k_hdr_movie_direct_play() {
        let s = one(r#"{"NowPlayingItem":{"Type":"Movie","MediaStreams":[{"Type":"Video","Height":2160,"Width":3840,"VideoRangeType":"DOVI"}]},"PlayState":{"PlayMethod":"DirectPlay"}}"#);
        assert_eq!(s, vec![st(Kind::Movie, Some(Quality::Uhd4kHdr), Mode::DirectPlay, false, 1)]);
    }

    #[test]
    fn session_1080p_episode_transcode() {
        let s = one(r#"{"NowPlayingItem":{"Type":"Episode","SeriesName":"Fixture Show Beta","MediaStreams":[{"Type":"Video","Height":1080,"Width":1920,"VideoRange":"SDR"}]},"PlayState":{"PlayMethod":"Transcode","IsPaused":true},"TranscodingInfo":{"IsVideoDirect":false}}"#);
        assert_eq!(s, vec![st(Kind::Episode, Some(Quality::Fhd1080Sdr), Mode::Transcode, true, 1)]);
    }

    #[test]
    fn session_audio_only_transcode() {
        let s = one(r#"{"NowPlayingItem":{"Type":"Movie","MediaStreams":[{"Type":"Video","Height":720,"Width":1280}]},"PlayState":{"PlayMethod":"Transcode"},"TranscodingInfo":{"IsVideoDirect":true,"IsAudioDirect":false}}"#);
        assert_eq!(s, vec![st(Kind::Movie, Some(Quality::Hd720), Mode::TranscodeAudio, false, 1)]);
    }

    #[test]
    fn session_without_video_is_other() {
        let s = one(r#"{"NowPlayingItem":{"Type":"AudioBook","MediaStreams":[{"Type":"Audio"}]},"PlayState":{"PlayMethod":"DirectPlay"}}"#);
        assert_eq!(s, vec![st(Kind::Other, None, Mode::DirectPlay, false, 1)]);
        let s = one(r#"{"NowPlayingItem":{"Type":"Movie","MediaStreams":null},"PlayState":null}"#);
        assert_eq!(s, vec![st(Kind::Other, None, Mode::DirectPlay, false, 1)]);
        assert_eq!(one(r#"{"UserName":"Idle","PlayState":{}}"#), vec![], "a session without a playing item is no stream");
    }

    #[test]
    fn anime_series_classified_anime() {
        let by_name = one(r#"{"NowPlayingItem":{"Type":"Episode","SeriesName":"FIXTURE ANIME GAMMA","MediaStreams":[{"Type":"Video","Height":1080}]}}"#);
        assert_eq!(by_name[0].kind, Kind::Anime);
        let by_folder = one(r#"{"NowPlayingItem":{"Type":"Episode","SeriesName":"Other Name","Path":"/media/anime/Fixture Anime Zeta/Season 1/e1.mkv","MediaStreams":[{"Type":"Video","Height":1080}]}}"#);
        assert_eq!(by_folder[0].kind, Kind::Anime);
        let plain = one(r#"{"NowPlayingItem":{"Type":"Episode","SeriesName":"Fixture Show Epsilon","MediaStreams":[{"Type":"Video","Height":1080}]}}"#);
        assert_eq!(plain[0].kind, Kind::Episode, "a standard Sonarr series stays Episode");
        let s: Vec<Session> = serde_json::from_str(r#"[{"NowPlayingItem":{"Type":"Episode","SeriesName":"Fixture Anime Gamma","MediaStreams":[{"Type":"Video","Height":1080}]}}]"#).unwrap();
        assert_eq!(streams(&s, &SeriesIndex::default())[0].kind, Kind::Episode, "no Sonarr data = Episode");
    }

    #[test]
    fn fixture_sessions_grouped() {
        let got = streams(&sessions(), &index());
        assert_eq!(
            got,
            vec![
                st(Kind::Movie, Some(Quality::Uhd4kHdr), Mode::DirectPlay, false, 2),
                st(Kind::Movie, Some(Quality::Fhd1080Hdr), Mode::DirectStream, false, 1),
                st(Kind::Episode, Some(Quality::Fhd1080Sdr), Mode::Transcode, false, 1),
                st(Kind::Episode, Some(Quality::Fhd1080Sdr), Mode::Transcode, true, 1),
                st(Kind::Anime, Some(Quality::Fhd1080Sdr), Mode::TranscodeAudio, false, 1),
                st(Kind::Other, None, Mode::DirectPlay, false, 1),
            ]
        );
        assert!(wants_series(&sessions()));
    }

    #[test]
    fn queue_series_aggregates_seasons_and_episodes() {
        let got = all_downloads();
        assert!(got.contains(&dl(DlState::Downloading, Kind::Anime, Some(Quality::Fhd1080Sdr), 1, 2, 4)), "{got:?}");
        assert!(got.contains(&dl(DlState::Problem, Kind::Episode, Some(Quality::Uhd4kSdr), 1, 1, 1)), "{got:?}");
        assert!(got.contains(&dl(DlState::WaitingNight, Kind::Episode, None, 1, 2, 18)), "requested series: monitored seasons with missing episodes, specials ignored: {got:?}");
    }

    #[test]
    fn night_waiting_from_request_state() {
        let got = all_downloads();
        assert!(got.contains(&dl(DlState::WaitingNight, Kind::Movie, Some(Quality::Fhd1080Sdr), 1, 0, 0)), "paused + id in night-waiting (case-insensitive): {got:?}");
        assert!(got.contains(&dl(DlState::WaitingNight, Kind::Episode, Some(Quality::Hd720), 1, 1, 2)), "{got:?}");
        assert!(got.contains(&dl(DlState::WaitingNight, Kind::Movie, None, 1, 0, 0)), "can wait, not in a queue, not unreleased: {got:?}");
        assert!(got.contains(&dl(DlState::WaitingRelease, Kind::Movie, None, 2, 0, 0)), "unreleased + no release found: {got:?}");
        assert!(got.contains(&dl(DlState::WaitingRelease, Kind::Anime, None, 1, 0, 0)), "{got:?}");
    }

    #[test]
    fn fixture_downloads_complete_and_ordered() {
        assert_eq!(
            all_downloads(),
            vec![
                dl(DlState::Downloading, Kind::Movie, Some(Quality::Uhd4kHdr), 1, 0, 0),
                dl(DlState::Downloading, Kind::Anime, Some(Quality::Fhd1080Sdr), 1, 2, 4),
                dl(DlState::Importing, Kind::Movie, Some(Quality::Fhd1080Sdr), 1, 0, 0),
                dl(DlState::Queued, Kind::Movie, Some(Quality::Fhd1080Sdr), 1, 0, 0),
                dl(DlState::Queued, Kind::Episode, Some(Quality::Fhd1080Sdr), 1, 1, 1),
                dl(DlState::Stalled, Kind::Movie, Some(Quality::Uhd4kSdr), 1, 0, 0),
                dl(DlState::Paused, Kind::Movie, Some(Quality::Hd720), 1, 0, 0),
                dl(DlState::WaitingNight, Kind::Movie, None, 1, 0, 0),
                dl(DlState::WaitingNight, Kind::Movie, Some(Quality::Fhd1080Sdr), 1, 0, 0),
                dl(DlState::WaitingNight, Kind::Episode, None, 1, 2, 18),
                dl(DlState::WaitingNight, Kind::Episode, Some(Quality::Hd720), 1, 1, 2),
                dl(DlState::WaitingRelease, Kind::Movie, None, 2, 0, 0),
                dl(DlState::WaitingRelease, Kind::Anime, None, 1, 0, 0),
                dl(DlState::Problem, Kind::Movie, Some(Quality::Hd720), 1, 0, 0),
                dl(DlState::Problem, Kind::Episode, Some(Quality::Uhd4kSdr), 1, 1, 1),
            ]
        );
    }

    fn state_of(json: &str, night: &[&str]) -> Option<DlState> {
        let r: QueueRecord = serde_json::from_str(json).unwrap();
        record_state(&r, &night.iter().map(|s| s.to_string()).collect())
    }

    #[test]
    fn every_queue_state_maps_to_a_category() {
        let cases: [(&str, Option<DlState>); 14] = [
            (r#"{"status":"downloading","trackedDownloadState":"downloading"}"#, Some(DlState::Downloading)),
            (r#"{"status":"delay","trackedDownloadState":"downloading"}"#, Some(DlState::Queued)),
            (r#"{"status":"queued","trackedDownloadState":"downloading"}"#, Some(DlState::Queued)),
            (r#"{"status":"warning","trackedDownloadStatus":"warning","trackedDownloadState":"downloading"}"#, Some(DlState::Stalled)),
            (r#"{"status":"downloadClientUnavailable","trackedDownloadState":"downloading"}"#, Some(DlState::Stalled)),
            (r#"{"status":"downloading","trackedDownloadStatus":"warning","trackedDownloadState":"downloading"}"#, Some(DlState::Stalled)),
            (r#"{"status":"paused","downloadId":"HAND"}"#, Some(DlState::Paused)),
            (r#"{"status":"paused","downloadId":"NIGHT"}"#, Some(DlState::WaitingNight)),
            (r#"{"status":"completed","trackedDownloadState":"importPending"}"#, Some(DlState::Importing)),
            (r#"{"status":"completed","trackedDownloadState":"downloading"}"#, Some(DlState::Importing)),
            (r#"{"status":"completed","trackedDownloadStatus":"warning","trackedDownloadState":"importBlocked"}"#, Some(DlState::Problem)),
            (r#"{"status":"failed","trackedDownloadState":"downloading"}"#, Some(DlState::Problem)),
            (r#"{"status":"completed","trackedDownloadState":"imported"}"#, None),
            (r#"{"status":"completed","trackedDownloadStatus":"warning","trackedDownloadState":"ignored"}"#, None),
        ];
        for (json, want) in cases {
            assert_eq!(state_of(json, &["night"]), want, "{json}");
        }
    }

    #[test]
    fn truncated_queues_are_detected() {
        let q: Queue = serde_json::from_str(r#"{"page":1,"pageSize":1,"totalRecords":250,"records":[{"movieId":1}]}"#).unwrap();
        assert_eq!(q.truncated(), Some((1, 250)));
        assert_eq!(serde_json::from_str::<Queue>(RADARR).unwrap().truncated(), None);
        assert_eq!(serde_json::from_str::<Queue>(r#"{"records":[]}"#).unwrap().truncated(), None, "no total: nothing to say");
    }

    #[test]
    fn night_label_needs_paused_and_listed_id() {
        let q: Queue = serde_json::from_str(r#"{"records":[{"movieId":1,"status":"paused","downloadId":"X"},{"movieId":2,"status":"downloading","downloadId":"Y"}]}"#).unwrap();
        let night: HashSet<String> = ["y".to_string()].into();
        let got = downloads(&q, &Queue::default(), &RequestState::default(), &SeriesIndex::default(), &night);
        assert_eq!(got, vec![dl(DlState::Downloading, Kind::Movie, None, 1, 0, 0), dl(DlState::Paused, Kind::Movie, None, 1, 0, 0)], "paused but not held for the night = paused by hand");
    }

    #[test]
    fn empty_and_null_sources_give_nothing() {
        let q: Queue = serde_json::from_str(r#"{"records":null}"#).unwrap();
        let rs: RequestState = serde_json::from_str("{}").unwrap();
        assert_eq!(downloads(&q, &q, &rs, &SeriesIndex::default(), &HashSet::new()), vec![]);
        assert!(!rs.has_tv());
        assert!(serde_json::from_str::<RequestState>(REQUESTS).unwrap().has_tv());
    }

    #[test]
    fn snapshot_has_no_titles_or_users() {
        let parts = (crate::state::StreamsPart { at: 1, streams: streams(&sessions(), &index()), series_unavailable: false }, crate::state::DownloadsPart { at: 1, list: all_downloads(), gaps: Default::default() });
        let out = (serde_json::to_string(&parts.0).unwrap() + &serde_json::to_string(&parts.1).unwrap()).to_lowercase();
        for secret in ["fixture", "jane", "john", "max muster", "erika", "idle person", "pilot", "night1", "abc123", "phone", "5001", "9005", "/data"] {
            assert!(!out.contains(secret), "{secret} leaked into {out}");
        }
    }

    #[test]
    fn the_series_index_is_reused_until_old_or_an_unknown_series_appears() {
        let rs: RequestState = serde_json::from_str(REQUESTS).unwrap();
        let sonarr: Queue = serde_json::from_str(SONARR).unwrap();
        let idx = SeriesIndex::build(&series(), 1000, &sonarr, &rs);
        assert!(!idx.needs_refresh(1000 + 60, &sonarr, &rs), "every series known or already looked up once");
        assert!(idx.needs_refresh(1000 + SERIES_TTL, &sonarr, &rs), "30 min old");
        assert!(idx.needs_refresh(900, &sonarr, &rs), "built in the future (clock step)");
        let more: Queue = serde_json::from_str(r#"{"records":[{"seriesId":299,"status":"downloading"}]}"#).unwrap();
        assert!(idx.needs_refresh(1060, &more, &rs), "a series id not seen before");
        let rs_more: RequestState = serde_json::from_str(r#"{"canWait":["tv/9999"]}"#).unwrap();
        assert!(idx.needs_refresh(1060, &sonarr, &rs_more), "a requested series not seen before");
        let again = SeriesIndex::build(&series(), 1060, &more, &rs_more);
        assert!(!again.needs_refresh(1120, &more, &rs_more), "still unknown after one lookup: no lookup every poll");
        assert!(SeriesIndex::default().needs_refresh(1060, &Queue::default(), &RequestState::default()), "never built");
    }

    #[test]
    fn the_series_index_keeps_no_titles() {
        let dbg = format!("{:?}", index()).to_lowercase();
        assert!(!dbg.contains("fixture") && !dbg.contains("/data"), "{dbg}");
    }

    #[test]
    fn gate_paths_are_get_paths_on_known_prefixes() {
        for p in GATE_PATHS {
            assert!(["/jellyfin/", "/radarr/", "/sonarr/", "/seerr/"].iter().any(|pre| p.starts_with(pre)), "{p}");
        }
    }
}
