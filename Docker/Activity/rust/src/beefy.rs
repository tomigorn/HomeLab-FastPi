//! beefy figures through the read-only activity-gate: the gate paths (a contract with the gate config on beefy),
//! typed parsers that keep only the fields the categories need, and the grouping into anonymous counts.

use std::collections::{BTreeMap, HashMap, HashSet};

use serde::Deserialize;

use crate::state::{Accel, DiskKind, DiskLoad, DlState, Download, History, Kind, Mode, Quality, Reason, SabPost, Stream, StreamLoad, Task, TaskLoad, WatchSummary};

/// Paths on the gate (`GATE_URL`); the gate on beefy allow-lists exactly these GET paths and injects the API keys.
pub const PATH_SESSIONS: &str = "/jellyfin/Sessions?ActiveWithinSeconds=60";
pub const PATH_RADARR_QUEUE: &str = "/radarr/api/v3/queue?pageSize=200&includeMovie=true";
pub const PATH_SONARR_QUEUE: &str = "/sonarr/api/v3/queue?pageSize=500&includeSeries=true&includeEpisode=true";
pub const PATH_SONARR_SERIES: &str = "/sonarr/api/v3/series";
pub const PATH_REQUEST_STATE: &str = "/seerr/request-state.json";
pub const PATH_NIGHT_WAITING: &str = "/seerr/night-waiting.json";
/// written every 60 s by beefy's idle watcher (beefy repo Server/8-Idle-Watcher)
pub const PATH_RESOURCES: &str = "/beefy/resources.json";

#[cfg_attr(not(test), allow(dead_code))]
pub const GATE_PATHS: [&str; 7] =
    [PATH_SESSIONS, PATH_RADARR_QUEUE, PATH_SONARR_QUEUE, PATH_SONARR_SERIES, PATH_REQUEST_STATE, PATH_NIGHT_WAITING, PATH_RESOURCES];

// ---------- beefy resources ----------

/// Older figures mean the idle watcher stopped writing (it writes every 60 s).
pub const RESOURCES_STALE: i64 = 180;
/// Clock skew between beefy and fastpi tolerated for a file "from the future".
const RESOURCES_SKEW: i64 = 30;

#[derive(Deserialize, Default)]
#[serde(default)]
pub struct Resources {
    v: u32,
    updated: i64,
    cpu_pct: Option<f64>,
    jellyfin_cpu_pct: Option<f64>,
    gpu_pct: Option<f64>,
    mem_used_bytes: Option<u64>,
    mem_total_bytes: Option<u64>,
    jellyfin_mem_bytes: Option<u64>,
    up_kbps: Option<u64>,
    dl_cpu_pct: Option<f64>,
    dl_mem_bytes: Option<u64>,
    dl_down_kbps: Option<u64>,
    disk_write_kbps: Option<u64>,
    sab_post: Option<String>,
    /// per stream ffmpeg, keyed by the hashed input file (`path_key`); None = not measured
    streams: Option<Vec<KeyedFigure>>,
    /// Jellyfin's background ffmpeg/ffprobe jobs
    background: Option<Vec<TaskFigure>>,
    cores_pct: Vec<Option<f64>>,
    swap_used_bytes: Option<u64>,
    swap_total_bytes: Option<u64>,
    down_kbps: Option<u64>,
    disks: Vec<DiskFigure>,
    hist: History,
}

/// Longest history kept from the file (the watcher sends 15 points).
const HIST_MAX: usize = 60;
/// More data disks than any pool here will have.
const DISKS_MAX: usize = 16;

#[derive(Deserialize, Default)]
#[serde(default)]
struct DiskFigure {
    kind: String,
    n: u8,
    busy_pct: Option<f64>,
    read_kbps: Option<u64>,
    write_kbps: Option<u64>,
    asleep: bool,
    used_bytes: Option<u64>,
    total_bytes: Option<u64>,
    yellow_pct: Option<f64>,
    orange_pct: Option<f64>,
    limit_pct: Option<f64>,
    busy_hist: Vec<Option<f64>>,
}

fn last_n<T: Clone>(v: &[T]) -> Vec<T> {
    v[v.len().saturating_sub(HIST_MAX)..].to_vec()
}

fn disk_load(d: &DiskFigure) -> Option<DiskLoad> {
    let kind = match d.kind.as_str() {
        "ssd" => DiskKind::Ssd,
        "hdd" => DiskKind::Hdd,
        "disk" => DiskKind::Disk,
        _ => return None,
    };
    if d.n == 0 || d.n as usize > DISKS_MAX {
        return None;
    }
    let pct = |p: Option<f64>| p.filter(|p| (0.0..=100.0).contains(p));
    let limit = |p: Option<f64>| p.filter(|p| *p > 0.0 && *p <= 100.0);
    let space = matches!((d.used_bytes, d.total_bytes), (Some(u), Some(t)) if t > 0 && u <= t);
    Some(DiskLoad {
        kind,
        n: d.n,
        busy_pct: pct(d.busy_pct),
        read_kbps: d.read_kbps,
        write_kbps: d.write_kbps,
        asleep: d.asleep,
        used_bytes: d.used_bytes.filter(|_| space),
        total_bytes: d.total_bytes.filter(|_| space),
        yellow_pct: limit(d.yellow_pct).filter(|_| space),
        orange_pct: limit(d.orange_pct).filter(|_| space),
        limit_pct: limit(d.limit_pct).filter(|_| space),
        busy_hist: last_n(&d.busy_hist.iter().map(|p| pct(*p)).collect::<Vec<_>>()),
    })
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct TaskFigure {
    task: String,
    cpu_pct: Option<f64>,
    gpu_pct: Option<f64>,
}

#[derive(Deserialize, Default, Clone, Copy, Debug, PartialEq)]
#[serde(default)]
pub struct StreamFigure {
    cpu_pct: Option<f64>,
    gpu_pct: Option<f64>,
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct KeyedFigure {
    key: String,
    #[serde(flatten)]
    fig: StreamFigure,
}

/// The idle watcher's key of a stream's input file: the first 16 hex digits of its SHA-256.
pub fn path_key(path: &str) -> String {
    crate::csp::sha256(path.as_bytes()).iter().take(8).map(|b| format!("{b:02x}")).collect()
}

impl Resources {
    /// The figures when fresh at `now` and of the known version; a percentage outside 0–100 is dropped.
    pub fn figures(&self, now: i64) -> Option<crate::state::Resources> {
        if self.v != 1 || !(-RESOURCES_SKEW..=RESOURCES_STALE).contains(&(now - self.updated)) {
            return None;
        }
        let pct = |p: Option<f64>| p.filter(|p| (0.0..=100.0).contains(p));
        Some(crate::state::Resources {
            updated: self.updated,
            cpu_pct: pct(self.cpu_pct),
            jellyfin_cpu_pct: pct(self.jellyfin_cpu_pct),
            gpu_pct: pct(self.gpu_pct),
            mem_used_bytes: self.mem_used_bytes,
            mem_total_bytes: self.mem_total_bytes,
            jellyfin_mem_bytes: self.jellyfin_mem_bytes,
            up_kbps: self.up_kbps,
            dl_cpu_pct: pct(self.dl_cpu_pct),
            dl_mem_bytes: self.dl_mem_bytes,
            dl_down_kbps: self.dl_down_kbps,
            disk_write_kbps: self.disk_write_kbps,
            sab_post: match self.sab_post.as_deref() {
                Some("unpacking") => Some(SabPost::Unpacking),
                Some("verifying") => Some(SabPost::Verifying),
                _ => None,
            },
            streams_cpu_pct: self.streams.as_ref().map(|s| (s.iter().filter_map(|k| pct(k.fig.cpu_pct)).sum::<f64>().min(100.0) * 10.0).round() / 10.0 + 0.0),
            streams_gpu_pct: self.streams.as_ref().map(|s| (s.iter().filter_map(|k| pct(k.fig.gpu_pct)).sum::<f64>().min(100.0) * 10.0).round() / 10.0 + 0.0),
            background: self
                .background
                .iter()
                .flatten()
                .map(|t| TaskLoad {
                    task: match t.task.as_str() {
                        "preview images" => Task::PreviewImages,
                        "chapter images" => Task::ChapterImages,
                        "intro/credits detection" => Task::IntroDetection,
                        "keyframe extraction" => Task::Keyframes,
                        "media probing" => Task::Probing,
                        _ => Task::Other,
                    },
                    cpu_pct: pct(t.cpu_pct),
                    gpu_pct: pct(t.gpu_pct),
                })
                .collect(),
            cores_pct: self.cores_pct.iter().filter_map(|p| pct(*p)).collect(),
            swap_used_bytes: self.swap_used_bytes,
            swap_total_bytes: self.swap_total_bytes,
            down_kbps: self.down_kbps,
            disks: self.disks.iter().filter_map(disk_load).take(DISKS_MAX).collect(),
            hist: History {
                cpu_pct: last_n(&self.hist.cpu_pct.iter().map(|p| pct(*p)).collect::<Vec<_>>()),
                mem_pct: last_n(&self.hist.mem_pct.iter().map(|p| pct(*p)).collect::<Vec<_>>()),
                gpu_pct: last_n(&self.hist.gpu_pct.iter().map(|p| pct(*p)).collect::<Vec<_>>()),
                down_kbps: last_n(&self.hist.down_kbps),
                up_kbps: last_n(&self.hist.up_kbps),
            },
        })
    }

    /// The per-stream ffmpeg figures by key, percentages outside 0–100 dropped; None = the watcher did not measure them.
    pub fn stream_figures(&self) -> Option<HashMap<String, StreamFigure>> {
        let pct = |p: Option<f64>| p.filter(|p| (0.0..=100.0).contains(p));
        Some(self.streams.as_ref()?.iter().map(|k| (k.key.clone(), StreamFigure { cpu_pct: pct(k.fig.cpu_pct), gpu_pct: pct(k.fig.gpu_pct) })).collect())
    }
}

// ---------- Jellyfin ----------

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "PascalCase")]
pub struct Session {
    now_playing_item: Option<Item>,
    play_state: Option<PlayState>,
    transcoding_info: Option<TranscodingInfo>,
    /// only counted (distinct users), never kept
    user_id: Option<String>,
    /// only classified LAN/remote, never kept
    remote_end_point: Option<String>,
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
    index: Option<i64>,
    bit_rate: Option<u64>,
}

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "PascalCase")]
struct PlayState {
    play_method: Option<String>,
    is_paused: Option<bool>,
    audio_stream_index: Option<i64>,
}

#[derive(Deserialize, Default)]
#[serde(default, rename_all = "PascalCase")]
struct TranscodingInfo {
    is_video_direct: Option<bool>,
    /// a list of reason names, or one comma-separated string on older servers
    transcode_reasons: Option<serde_json::Value>,
    hardware_acceleration_type: Option<String>,
    bitrate: Option<u64>,
}

fn reason(name: &str) -> Reason {
    match name.trim() {
        "ContainerNotSupported" => Reason::Container,
        "SubtitleCodecNotSupported" => Reason::Subtitles,
        "VideoRangeTypeNotSupported" => Reason::HdrToneMap,
        "ContainerBitrateExceedsLimit" | "VideoBitrateNotSupported" | "AudioBitrateNotSupported" => Reason::Bitrate,
        n if n.starts_with("Audio") || n == "SecondaryAudioNotSupported" => Reason::Audio,
        n if n.starts_with("Video") || matches!(n, "RefFramesNotSupported" | "AnamorphicVideoNotSupported" | "InterlacedVideoNotSupported") => Reason::VideoCodec,
        _ => Reason::Other,
    }
}

fn reasons(t: &TranscodingInfo) -> Vec<Reason> {
    let names: Vec<String> = match &t.transcode_reasons {
        Some(serde_json::Value::Array(a)) => a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect(),
        Some(serde_json::Value::String(s)) => s.split(',').map(str::to_string).collect(),
        _ => Vec::new(),
    };
    let set: std::collections::BTreeSet<Reason> = names.iter().filter(|n| !n.trim().is_empty()).map(|n| reason(n)).collect();
    set.into_iter().collect()
}

fn accel(t: &TranscodingInfo) -> Option<Accel> {
    Some(match t.hardware_acceleration_type.as_deref()?.to_ascii_lowercase().as_str() {
        "none" | "" => Accel::Software,
        "qsv" => Accel::Qsv,
        "vaapi" => Accel::Vaapi,
        _ => Accel::OtherHardware,
    })
}

/// A private, loopback or link-local address (home, VPN); None = not an address. Accepts `[v6]:port` and `v4:port`.
pub fn is_lan(addr: &str) -> Option<bool> {
    use std::net::IpAddr;
    let ip = ip_of(addr)?;
    let v4 = match ip {
        IpAddr::V4(v) => Some(v),
        IpAddr::V6(v) => v.to_ipv4_mapped(),
    };
    Some(match (v4, ip) {
        (Some(v), _) => v.is_private() || v.is_loopback() || v.is_link_local() || (v.octets()[0] == 100 && (v.octets()[1] & 0xC0) == 64),
        (None, IpAddr::V6(v)) => v.is_loopback() || (v.segments()[0] & 0xfe00) == 0xfc00 || (v.segments()[0] & 0xffc0) == 0xfe80,
        _ => false,
    })
}

fn ip_of(addr: &str) -> Option<std::net::IpAddr> {
    let a = addr.trim();
    let a = a.split_once('%').map_or(a, |(h, _)| h);
    a.parse().ok().or_else(|| a.strip_prefix('[').and_then(|r| r.split_once(']')).and_then(|(h, _)| h.parse().ok())).or_else(|| a.rsplit_once(':').and_then(|(h, _)| h.parse().ok()))
}

/// Some(true) = LAN, Some(false) = remote. A tunnel peer (`TUNNEL_PEERS`, the docker gateway the Cloudflare tunnel's requests arrive from) is remote although private.
pub fn location(addr: &str, tunnel: &crate::api::Allow) -> Option<bool> {
    if ip_of(addr).is_some_and(|ip| tunnel.contains(ip)) {
        return Some(false);
    }
    is_lan(addr)
}

/// bits/s a session sends now: the transcode's output, else the video stream plus the selected (or first) audio stream.
fn bitrate(s: &Session, item: &Item) -> Option<u64> {
    if let Some(b) = s.transcoding_info.as_ref().and_then(|t| t.bitrate).filter(|_| s.play_state.as_ref().and_then(|p| p.play_method.as_deref()) == Some("Transcode")) {
        return Some(b);
    }
    let ms = item.media_streams.as_deref().unwrap_or_default();
    let video = ms.iter().find(|m| m.kind.as_deref() == Some("Video")).and_then(|m| m.bit_rate);
    let want = s.play_state.as_ref().and_then(|p| p.audio_stream_index);
    let audio = ms.iter().filter(|m| m.kind.as_deref() == Some("Audio")).find(|m| want.is_none() || m.index == want).and_then(|m| m.bit_rate);
    match (video, audio) {
        (None, None) => None,
        (v, a) => Some(v.unwrap_or(0) + a.unwrap_or(0)),
    }
}

/// Bitrate, LAN/remote and distinct users over the playing sessions; the addresses and ids die with the sessions.
pub fn summary(sessions: &[Session], tunnel: &crate::api::Allow) -> WatchSummary {
    let mut out = WatchSummary::default();
    let mut people: HashSet<&str> = HashSet::new();
    let mut bits: Option<u64> = None;
    for (s, item) in sessions.iter().filter_map(|s| s.now_playing_item.as_ref().map(|i| (s, i))) {
        match s.remote_end_point.as_deref().and_then(|a| location(a, tunnel)) {
            Some(true) => out.lan += 1,
            Some(false) => out.remote += 1,
            None => {}
        }
        if let Some(u) = s.user_id.as_deref() {
            people.insert(u);
        }
        let paused = s.play_state.as_ref().and_then(|p| p.is_paused).unwrap_or(false);
        if let Some(b) = bitrate(s, item).filter(|_| !paused) {
            bits = Some(bits.unwrap_or(0) + b);
        }
    }
    out.people = people.len() as u32;
    out.bitrate_kbps = bits.map(|b| b / 1000);
    out
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
    let kind = match item.kind.as_deref() {
        Some("Movie") => Kind::Movie,
        Some("Episode") if anime.is_anime_item(item) => Kind::Anime,
        Some("Episode") => Kind::Episode,
        Some("Audio") => Kind::Music,
        Some("AudioBook") => Kind::Audiobook,
        Some("TvChannel" | "LiveTvChannel" | "Program" | "LiveTvProgram") => Kind::LiveTv,
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
    let t = s.transcoding_info.as_ref().filter(|_| matches!(mode, Mode::Transcode | Mode::TranscodeAudio));
    Some(Stream {
        kind,
        quality,
        mode,
        paused: ps.and_then(|p| p.is_paused).unwrap_or(false),
        n: 1,
        accel: t.filter(|_| mode == Mode::Transcode).and_then(accel),
        reasons: t.map(reasons).unwrap_or_default(),
    })
}

/// Playing sessions grouped by kind × quality × mode × paused; sessions without a playing item are not streams.
pub fn streams(sessions: &[Session], anime: &SeriesIndex) -> Vec<Stream> {
    type G = (Kind, Option<Quality>, Mode, bool, Option<Accel>, Vec<Reason>);
    let mut groups: BTreeMap<G, u32> = BTreeMap::new();
    for s in sessions.iter().filter_map(|s| stream_of(s, anime)) {
        *groups.entry((s.kind, s.quality, s.mode, s.paused, s.accel, s.reasons)).or_default() += 1;
    }
    groups.into_iter().map(|((kind, quality, mode, paused, accel, reasons), n)| Stream { kind, quality, mode, paused, n, accel, reasons }).collect()
}

/// One row per playing session: its category, its bitrate, and its ffmpeg's CPU/GPU when the watcher measured one for exactly this session's file.
/// Two sessions on the same file cannot be told apart: neither gets figures. A file key lives only for this matching.
pub fn stream_loads(sessions: &[Session], anime: &SeriesIndex, figures: Option<&HashMap<String, StreamFigure>>) -> Vec<StreamLoad> {
    let playing: Vec<(&Session, &Item, Stream, Option<String>)> = sessions
        .iter()
        .filter_map(|s| Some((s, s.now_playing_item.as_ref()?, stream_of(s, anime)?)))
        .map(|(s, i, st)| (s, i, st, i.path.as_deref().map(path_key)))
        .collect();
    let mut seen: HashMap<&str, u32> = HashMap::new();
    for k in playing.iter().filter_map(|p| p.3.as_deref()) {
        *seen.entry(k).or_default() += 1;
    }
    let mut out: Vec<StreamLoad> = playing
        .iter()
        .map(|(s, item, st, key)| {
            let fig = key.as_deref().filter(|k| seen.get(k) == Some(&1)).and_then(|k| figures?.get(k)).copied().unwrap_or_default();
            StreamLoad {
                kind: st.kind,
                quality: st.quality,
                mode: st.mode,
                paused: st.paused,
                cpu_pct: fig.cpu_pct,
                gpu_pct: fig.gpu_pct,
                kbps: bitrate(s, item).filter(|_| !st.paused).map(|b| b / 1000),
            }
        })
        .collect();
    out.sort_by_key(|l| (l.paused, std::cmp::Reverse(l.kbps), l.kind, l.quality, l.mode));
    out
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
    sizeleft: Option<f64>,
    timeleft: Option<String>,
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
    low_tariff: Option<bool>,
}

impl NightWaiting {
    /// The night window is open (night-downloads.py `low_tariff`).
    pub fn open(&self) -> Option<bool> {
        self.low_tariff
    }

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

/// Radarr/Sonarr `timeleft`: `hh:mm:ss` or `d.hh:mm:ss` → seconds.
fn parse_timeleft(t: &str) -> Option<u64> {
    let (days, hms) = match t.split_once('.') {
        Some((d, rest)) if !d.contains(':') => (d.parse::<u64>().ok()?, rest),
        _ => (0, t),
    };
    let p: Vec<u64> = hms.split(':').map(|x| x.split('.').next().unwrap_or("").parse().ok()).collect::<Option<_>>()?;
    let [h, m, s] = p[..] else { return None };
    Some(days * 86_400 + h * 3600 + m * 60 + s)
}

/// (download key, size left, time left) of a queue record; a record without download id counts as its own download.
fn progress(r: &QueueRecord, n: usize) -> (String, Option<u64>, Option<u64>) {
    let key = r.download_id.as_deref().map(str::to_lowercase).unwrap_or_else(|| format!("#{n}"));
    (key, r.sizeleft.filter(|x| x.is_finite() && *x >= 0.0).map(|x| x as u64), r.timeleft.as_deref().and_then(parse_timeleft))
}

#[derive(Default)]
struct Bucket {
    items: HashSet<String>,
    seasons: HashSet<(String, i64)>,
    episodes: u32,
    extra_seasons: u32,
    eta: Option<u64>,
    left: HashMap<String, u64>,
}

impl Bucket {
    fn add_progress(&mut self, (key, left, eta): (String, Option<u64>, Option<u64>)) {
        if let Some(l) = left {
            let e = self.left.entry(key).or_default();
            *e = (*e).max(l);
        }
        if eta.is_some() {
            self.eta = self.eta.max(eta);
        }
    }
}

type Key = (DlState, Kind, Option<Quality>);

/// Queues, request state and series grouped into state × kind × quality with item, season and episode counts.
pub fn downloads(radarr: &Queue, sonarr: &Queue, rs: &RequestState, series: &SeriesIndex, night: &HashSet<String>) -> Vec<Download> {
    let mut buckets: BTreeMap<Key, Bucket> = BTreeMap::new();

    type Movie = (DlState, Option<Quality>, Vec<(String, Option<u64>, Option<u64>)>);
    let mut movies: HashMap<i64, Movie> = HashMap::new();
    for (n, r) in radarr.records.iter().flatten().enumerate() {
        let Some(id) = r.movie_id.filter(|&id| id > 0) else { continue };
        let Some(st) = record_state(r, night) else { continue };
        let q = record_quality(r);
        let m = movies.entry(id).or_insert((st, q, Vec::new()));
        if rank(st) > rank(m.0) {
            (m.0, m.1) = (st, q);
        }
        m.2.push(progress(r, n));
    }
    for (id, (st, q, prog)) in movies {
        let b = buckets.entry((st, Kind::Movie, q)).or_default();
        b.items.insert(format!("m{id}"));
        for p in prog {
            b.add_progress(p);
        }
    }

    for (n, r) in sonarr.records.iter().flatten().enumerate() {
        let Some(id) = r.series_id.filter(|&id| id > 0) else { continue };
        let Some(st) = record_state(r, night) else { continue };
        let anime = r.series.as_ref().and_then(|s| s.series_type.as_deref()).is_some_and(|t| t.eq_ignore_ascii_case("anime"));
        let b = buckets.entry((st, if anime { Kind::Anime } else { Kind::Episode }, record_quality(r))).or_default();
        b.items.insert(format!("s{id}"));
        b.add_progress(progress(r, n));
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
            eta: b.eta,
            left: (!b.left.is_empty()).then(|| b.left.values().sum()),
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
    const RESOURCES: &str = include_str!("../fixtures/resources.json");

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
        Stream { kind, quality, mode, paused, n, accel: None, reasons: vec![] }
    }
    fn tr(s: Stream, accel: Option<Accel>, reasons: &[Reason]) -> Stream {
        Stream { accel, reasons: reasons.to_vec(), ..s }
    }
    fn dl(state: DlState, kind: Kind, quality: Option<Quality>, items: u32, seasons: u32, episodes: u32) -> Download {
        Download { state, kind, quality, items, seasons, episodes, eta: None, left: None }
    }
    fn left(d: Download, eta: Option<u64>, left: Option<u64>) -> Download {
        Download { eta, left, ..d }
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
    fn sessions_are_kinds_by_item_type() {
        let kind = |t: &str| one(&format!(r#"{{"NowPlayingItem":{{"Type":"{t}","MediaStreams":[{{"Type":"Audio"}}]}},"PlayState":{{"PlayMethod":"DirectPlay"}}}}"#))[0].kind;
        assert_eq!(kind("Audio"), Kind::Music);
        assert_eq!(kind("AudioBook"), Kind::Audiobook);
        assert_eq!(kind("TvChannel"), Kind::LiveTv);
        assert_eq!(kind("LiveTvChannel"), Kind::LiveTv);
        assert_eq!(kind("Program"), Kind::LiveTv);
        assert_eq!(kind("MusicVideo"), Kind::Other);
        assert_eq!(kind("Trailer"), Kind::Other);
        let s = one(r#"{"NowPlayingItem":{"Type":"AudioBook","MediaStreams":[{"Type":"Audio"}]},"PlayState":{"PlayMethod":"DirectPlay"}}"#);
        assert_eq!(s, vec![st(Kind::Audiobook, None, Mode::DirectPlay, false, 1)]);
        let s = one(r#"{"NowPlayingItem":{"Type":"Movie","MediaStreams":null},"PlayState":null}"#);
        assert_eq!(s, vec![st(Kind::Movie, None, Mode::DirectPlay, false, 1)], "the type decides; no video stream known = no quality");
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
                st(Kind::Movie, Some(Quality::Uhd4kHdr), Mode::DirectPlay, true, 1),
                st(Kind::Movie, Some(Quality::Fhd1080Hdr), Mode::DirectStream, false, 1),
                tr(st(Kind::Episode, Some(Quality::Fhd1080Sdr), Mode::Transcode, false, 1), Some(Accel::Qsv), &[Reason::HdrToneMap, Reason::Bitrate]),
                tr(st(Kind::Episode, Some(Quality::Fhd1080Sdr), Mode::Transcode, true, 1), Some(Accel::Qsv), &[Reason::Subtitles]),
                tr(st(Kind::Anime, Some(Quality::Fhd1080Sdr), Mode::TranscodeAudio, false, 1), None, &[Reason::Audio]),
                st(Kind::Music, None, Mode::DirectPlay, false, 1),
            ]
        );
        assert!(wants_series(&sessions()));
    }

    #[test]
    fn transcode_reasons_grouped_readably() {
        let reasons = |r: &str| one(&format!(r#"{{"NowPlayingItem":{{"Type":"Movie"}},"PlayState":{{"PlayMethod":"Transcode"}},"TranscodingInfo":{{"IsVideoDirect":false,"TranscodeReasons":{r}}}}}"#))[0].reasons.clone();
        assert_eq!(
            reasons(r#"["DirectPlayError","AudioChannelsNotSupported","ContainerBitrateExceedsLimit","VideoRangeTypeNotSupported","SubtitleCodecNotSupported","ContainerNotSupported","VideoLevelNotSupported","VideoCodecNotSupported","AudioBitrateNotSupported"]"#),
            vec![Reason::VideoCodec, Reason::Container, Reason::Subtitles, Reason::HdrToneMap, Reason::Bitrate, Reason::Audio, Reason::Other]
        );
        assert_eq!(reasons(r#""SubtitleCodecNotSupported, AudioCodecNotSupported""#), vec![Reason::Subtitles, Reason::Audio], "older servers send one comma-separated string");
        assert_eq!(reasons("null"), vec![]);
        let direct = one(r#"{"NowPlayingItem":{"Type":"Movie"},"PlayState":{"PlayMethod":"DirectPlay"},"TranscodingInfo":{"TranscodeReasons":["ContainerNotSupported"],"HardwareAccelerationType":"qsv"}}"#);
        assert_eq!((direct[0].reasons.len(), direct[0].accel), (0, None), "only a transcode has reasons and an encoder");
    }

    #[test]
    fn hardware_or_software_transcode() {
        let accel = |a: &str| one(&format!(r#"{{"NowPlayingItem":{{"Type":"Movie"}},"PlayState":{{"PlayMethod":"Transcode"}},"TranscodingInfo":{{"IsVideoDirect":false,"HardwareAccelerationType":{a}}}}}"#))[0].accel;
        assert_eq!(accel(r#""qsv""#), Some(Accel::Qsv));
        assert_eq!(accel(r#""vaapi""#), Some(Accel::Vaapi));
        assert_eq!(accel(r#""nvenc""#), Some(Accel::OtherHardware));
        assert_eq!(accel(r#""none""#), Some(Accel::Software));
        assert_eq!(accel("null"), None);
        let audio = one(r#"{"NowPlayingItem":{"Type":"Movie"},"PlayState":{"PlayMethod":"Transcode"},"TranscodingInfo":{"IsVideoDirect":true,"HardwareAccelerationType":"qsv"}}"#);
        assert_eq!(audio[0].accel, None, "an audio-only transcode does not use the video encoder");
    }

    #[test]
    fn bitrate_location_and_people_without_keeping_them() {
        let s = summary(&sessions(), &tunnel());
        assert_eq!(s, WatchSummary { bitrate_kbps: Some(142_960), lan: 4, remote: 4, people: 5 }, "paused streams send nothing; direct = video + selected audio, transcode = its output bitrate; the tunnel peer is remote");
        assert_eq!(summary(&[], &tunnel()), WatchSummary { bitrate_kbps: None, lan: 0, remote: 0, people: 0 });
        let lan_only = summary(&sessions(), &crate::api::Allow::default());
        assert_eq!((lan_only.lan, lan_only.remote), (5, 3), "without TUNNEL_PEERS 172.24.0.1 is just a private address");
    }

    fn tunnel() -> crate::api::Allow {
        crate::api::Allow::parse("172.24.0.1/32").unwrap()
    }

    #[test]
    fn tunnel_peers_are_remote_other_private_addresses_lan() {
        let loc = |a: &str| location(a, &tunnel());
        assert_eq!(loc("172.24.0.1"), Some(false), "internet clients reach Jellyfin through the tunnel from the docker gateway");
        assert_eq!(loc("::ffff:172.24.0.1"), Some(false));
        assert_eq!(loc("172.24.0.5"), Some(true), "the VPN container stays LAN");
        assert_eq!(loc("192.168.1.50"), Some(true));
        assert_eq!(loc("fe80::1%eth0"), Some(true), "IPv6 link-local with a zone");
        assert_eq!(loc("fd00::5"), Some(true));
        assert_eq!(loc("203.0.113.7"), Some(false));
    }

    #[test]
    fn private_addresses_are_lan() {
        for a in ["192.168.1.5", "10.8.0.3", "172.24.0.5", "127.0.0.1", "100.64.1.1", "169.254.1.1", "::1", "fe80::1", "fd00::5", "::ffff:192.168.1.9", "[::1]:8096", "192.168.1.5:51000"] {
            assert_eq!(is_lan(a), Some(true), "{a}");
        }
        for a in ["203.0.113.7", "8.8.8.8", "172.32.0.1", "2001:db8::1", "::ffff:203.0.113.9"] {
            assert_eq!(is_lan(a), Some(false), "{a}");
        }
        assert_eq!(is_lan("nonsense"), None);
    }

    #[test]
    fn time_and_size_left_per_row() {
        assert_eq!(parse_timeleft("00:40:00"), Some(2400));
        assert_eq!(parse_timeleft("1.02:03:04"), Some(93_784));
        assert_eq!(parse_timeleft("bad"), None);
        let got = all_downloads();
        assert!(got.contains(&left(dl(DlState::Downloading, Kind::Movie, Some(Quality::Uhd4kHdr), 1, 0, 0), Some(4205), Some(8_000_000_000))), "two downloads of one movie: longest time, both sizes: {got:?}");
        assert!(got.contains(&left(dl(DlState::Downloading, Kind::Anime, Some(Quality::Fhd1080Sdr), 1, 2, 4), Some(93_784), Some(4_000_000_000))), "one season pack on four episode records counts once: {got:?}");
        assert!(got.contains(&left(dl(DlState::Stalled, Kind::Movie, Some(Quality::Uhd4kSdr), 1, 0, 0), None, Some(2_000_000_000))), "no time known: {got:?}");
    }

    #[test]
    fn queue_series_aggregates_seasons_and_episodes() {
        let got = all_downloads();
        assert!(got.contains(&left(dl(DlState::Downloading, Kind::Anime, Some(Quality::Fhd1080Sdr), 1, 2, 4), Some(93_784), Some(4_000_000_000))), "{got:?}");
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
                left(dl(DlState::Downloading, Kind::Movie, Some(Quality::Uhd4kHdr), 1, 0, 0), Some(4205), Some(8_000_000_000)),
                left(dl(DlState::Downloading, Kind::Anime, Some(Quality::Fhd1080Sdr), 1, 2, 4), Some(93_784), Some(4_000_000_000)),
                dl(DlState::Importing, Kind::Movie, Some(Quality::Fhd1080Sdr), 1, 0, 0),
                dl(DlState::Queued, Kind::Movie, Some(Quality::Fhd1080Sdr), 1, 0, 0),
                dl(DlState::Queued, Kind::Episode, Some(Quality::Fhd1080Sdr), 1, 1, 1),
                left(dl(DlState::Stalled, Kind::Movie, Some(Quality::Uhd4kSdr), 1, 0, 0), None, Some(2_000_000_000)),
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
    fn night_window_state_from_night_waiting() {
        assert_eq!(serde_json::from_str::<NightWaiting>(NIGHT).unwrap().open(), Some(false));
        assert_eq!(serde_json::from_str::<NightWaiting>(r#"{"waiting":[],"low_tariff":true}"#).unwrap().open(), Some(true));
        assert_eq!(serde_json::from_str::<NightWaiting>(r#"{"waiting":[]}"#).unwrap().open(), None);
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
        let parts = (crate::state::StreamsPart { at: 1, streams: streams(&sessions(), &index()), series_unavailable: false, summary: Default::default(), resources: None, loads: vec![] }, crate::state::DownloadsPart { at: 1, list: all_downloads(), gaps: Default::default(), night_open: None });
        let out = (serde_json::to_string(&parts.0).unwrap() + &serde_json::to_string(&parts.1).unwrap()).to_lowercase();
        let out = out + &serde_json::to_string(&summary(&sessions(), &tunnel())).unwrap();
        for secret in ["fixture", "jane", "john", "max muster", "erika", "idle person", "pilot", "night1", "abc123", "phone", "5001", "9005", "/data", "u-", "tess", "tablet", "omega", "172.24", "203.0.113", "192.168", "10.8.0", "fe80", "ffff"] {
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
            assert!(["/jellyfin/", "/radarr/", "/sonarr/", "/seerr/", "/beefy/"].iter().any(|pre| p.starts_with(pre)), "{p}");
        }
        assert!(GATE_PATHS.contains(&PATH_RESOURCES));
    }

    #[test]
    fn resources_are_numbers_from_a_fresh_file() {
        let r: Resources = serde_json::from_str(RESOURCES).unwrap();
        let at = 1_794_861_563;
        let want = crate::state::Resources {
            updated: at,
            cpu_pct: Some(23.1),
            jellyfin_cpu_pct: Some(18.0),
            gpu_pct: Some(41.0),
            mem_used_bytes: Some(9_878_000_000),
            mem_total_bytes: Some(65_882_521_600),
            jellyfin_mem_bytes: Some(982_011_904),
            up_kbps: Some(27_013),
            dl_cpu_pct: Some(22.0),
            dl_mem_bytes: Some(1_181_116_006),
            dl_down_kbps: Some(432_000),
            disk_write_kbps: Some(960_000),
            sab_post: Some(SabPost::Unpacking),
            streams_cpu_pct: Some(7.5),
            streams_gpu_pct: Some(44.0),
            background: vec![TaskLoad { task: Task::PreviewImages, cpu_pct: Some(3.2), gpu_pct: Some(22.0) }, TaskLoad { task: Task::Other, cpu_pct: Some(0.1), gpu_pct: None }],
            cores_pct: vec![75.0, 10.0, 2.5],
            swap_used_bytes: Some(48_234_496),
            swap_total_bytes: Some(8_589_930_496),
            down_kbps: Some(1_888),
            disks: vec![
                DiskLoad { kind: DiskKind::Ssd, n: 1, busy_pct: Some(50.0), read_kbps: Some(1_638), write_kbps: Some(12_288), asleep: false,
                           used_bytes: Some(6_374_687_449_088), total_bytes: Some(7_937_302_708_224), yellow_pct: Some(70.0), orange_pct: Some(75.0), limit_pct: Some(80.0), busy_hist: vec![Some(1.0), None, Some(50.0)] },
                DiskLoad { kind: DiskKind::Ssd, n: 2, busy_pct: Some(0.1), read_kbps: Some(2), write_kbps: Some(2_183), asleep: false,
                           used_bytes: Some(906_611_556_352), total_bytes: Some(7_937_302_708_224), yellow_pct: Some(70.0), orange_pct: Some(75.0), limit_pct: Some(80.0), busy_hist: vec![] },
                DiskLoad { kind: DiskKind::Hdd, n: 1, busy_pct: Some(0.0), read_kbps: Some(0), write_kbps: Some(0), asleep: true,
                           used_bytes: Some(574_425_268_224), total_bytes: Some(29_998_208_495_616), yellow_pct: Some(80.0), orange_pct: Some(85.0), limit_pct: Some(90.0), busy_hist: vec![] },
            ],
            hist: History { cpu_pct: vec![Some(3.0), Some(23.1)], mem_pct: vec![Some(14.0), Some(15.0)], gpu_pct: vec![None, Some(41.0)], down_kbps: vec![Some(900), Some(1_888)], up_kbps: vec![Some(100), Some(27_013)] },
        };
        assert_eq!(r.figures(at + 30), Some(want.clone()), "a disk of an unknown kind is left out");
        assert_eq!(r.figures(at + RESOURCES_STALE), Some(want));
        assert_eq!(r.figures(at + RESOURCES_STALE + 1), None, "the watcher writes every 60 s: older = it stopped");
        assert!(r.figures(at - 20).is_some(), "a little clock skew between the hosts");
        assert_eq!(r.figures(at - 31), None, "far in the future");
    }

    #[test]
    fn resources_leave_unknown_figures_empty_and_refuse_other_versions() {
        let r: Resources = serde_json::from_str(r#"{"v":1,"updated":100,"interval_s":60,"cpu_pct":3.0,"extra":"x"}"#).unwrap();
        let f = r.figures(110).unwrap();
        assert_eq!((f.cpu_pct, f.gpu_pct, f.jellyfin_cpu_pct, f.mem_used_bytes, f.up_kbps), (Some(3.0), None, None, None, None));
        let r: Resources = serde_json::from_str(r#"{"v":2,"updated":100,"cpu_pct":3.0}"#).unwrap();
        assert_eq!(r.figures(110), None);
        let r: Resources = serde_json::from_str(r#"{"v":1,"updated":100,"cpu_pct":-5,"gpu_pct":250}"#).unwrap();
        let f = r.figures(110).unwrap();
        assert_eq!((f.cpu_pct, f.gpu_pct), (None, None), "out of range = not a reading");
        assert_eq!((f.streams_cpu_pct, f.streams_gpu_pct, f.background), (None, None, vec![]), "no lists = not measured");
        assert_eq!(r.stream_figures(), None, "no streams list = not measured");
        assert_eq!((f.cores_pct.len(), f.disks.len(), f.hist.cpu_pct.len()), (0, 0, 0), "no overview lists = not measured");
        let long: Vec<String> = (0..70).map(|i| i.to_string()).collect();
        let r: Resources = serde_json::from_str(&format!(
            r#"{{"v":1,"updated":100,"cores_pct":[5,250,-1],"disks":[{{"kind":"ssd","n":1,"busy_pct":250,"used_bytes":9,"total_bytes":5,"limit_pct":180,"busy_hist":[{l}]}},{{"kind":"hdd","n":0}}],"hist":{{"cpu_pct":[{l}]}}}}"#,
            l = long.join(",")
        ))
        .unwrap();
        let f = r.figures(110).unwrap();
        assert_eq!(f.cores_pct, vec![5.0], "readings outside 0-100 dropped");
        assert_eq!(f.disks.len(), 1, "a disk numbered 0 is not a disk");
        let d = &f.disks[0];
        assert_eq!((d.busy_pct, d.used_bytes, d.total_bytes, d.limit_pct), (None, None, None, None), "used over total = no space figures");
        assert_eq!((d.busy_hist.len(), d.busy_hist[0]), (60, Some(10.0)), "the last 60 history points");
        assert_eq!(f.hist.cpu_pct.len(), 60);
        let r: Resources = serde_json::from_str(r#"{"v":1,"updated":100,"sab_post":"exploding","streams":[{"key":"a","cpu_pct":140,"gpu_pct":3}]}"#).unwrap();
        assert_eq!(r.figures(110).unwrap().sab_post, None, "an unknown post-processing word is dropped");
        let f = r.stream_figures().unwrap();
        assert_eq!((f["a"].cpu_pct, f["a"].gpu_pct), (None, Some(3.0)));
        let r: Resources = serde_json::from_str(r#"{"v":1,"updated":100,"streams":[]}"#).unwrap();
        let f = r.figures(110).unwrap();
        assert_eq!(serde_json::to_string(&(f.streams_cpu_pct, f.streams_gpu_pct)).unwrap(), "[0.0,0.0]", "no stream running: 0, never -0");
    }

    #[test]
    fn path_key_matches_the_idle_watcher() {
        assert_eq!(path_key("/data/tv/Fixture Show Gamma/Season 01/e7.mkv"), "455003ea70a9bcad", "hashlib.sha256(path).hexdigest()[:16]");
    }

    fn sl(kind: Kind, quality: Option<Quality>, mode: Mode, paused: bool, cpu: Option<f64>, gpu: Option<f64>, kbps: Option<u64>) -> StreamLoad {
        StreamLoad { kind, quality, mode, paused, cpu_pct: cpu, gpu_pct: gpu, kbps }
    }

    #[test]
    fn one_row_per_session_with_only_measured_figures() {
        let r: Resources = serde_json::from_str(RESOURCES).unwrap();
        let figs = r.stream_figures().unwrap();
        let rows = stream_loads(&sessions(), &index(), Some(&figs));
        let (q4h, q1h, q1s) = (Some(Quality::Uhd4kHdr), Some(Quality::Fhd1080Hdr), Some(Quality::Fhd1080Sdr));
        assert_eq!(
            rows,
            vec![
                sl(Kind::Movie, q4h, Mode::DirectPlay, false, None, None, Some(60_640)),
                sl(Kind::Movie, q4h, Mode::DirectPlay, false, None, None, Some(40_000)),
                sl(Kind::Movie, q1h, Mode::DirectStream, false, Some(0.4), None, Some(20_000)),
                sl(Kind::Anime, q1s, Mode::TranscodeAudio, false, None, None, Some(12_000)),
                sl(Kind::Episode, q1s, Mode::Transcode, false, Some(2.1), Some(41.0), Some(10_000)),
                sl(Kind::Music, None, Mode::DirectPlay, false, None, None, Some(320)),
                sl(Kind::Movie, q4h, Mode::DirectPlay, true, None, None, None),
                sl(Kind::Episode, q1s, Mode::Transcode, true, None, None, None),
            ],
            "direct play has no ffmpeg: no CPU; the unmatched key ffff… is nobody's; paused: no bitrate"
        );
        let none = stream_loads(&sessions(), &index(), None);
        assert!(none.iter().all(|l| l.cpu_pct.is_none() && l.gpu_pct.is_none()), "no figures from beefy: nothing measured");
        assert_eq!(none.len(), 8);
    }

    #[test]
    fn two_sessions_on_one_file_get_no_figures() {
        let s = r#"{"NowPlayingItem":{"Type":"Movie","Path":"/data/tv/Fixture Show Gamma/Season 01/e7.mkv","MediaStreams":[{"Type":"Video","Height":1080}]},"PlayState":{"PlayMethod":"Transcode"},"TranscodingInfo":{"Bitrate":8000000}}"#;
        let two: Vec<Session> = vec![serde_json::from_str(s).unwrap(), serde_json::from_str(s).unwrap()];
        let r: Resources = serde_json::from_str(RESOURCES).unwrap();
        let rows = stream_loads(&two, &index(), r.stream_figures().as_ref());
        assert_eq!(rows.len(), 2);
        assert!(rows.iter().all(|l| l.cpu_pct.is_none() && l.kbps == Some(8000)), "{rows:?}");
        let rows = stream_loads(&two[..1], &index(), r.stream_figures().as_ref());
        assert_eq!((rows[0].cpu_pct, rows[0].gpu_pct), (Some(2.1), Some(41.0)));
    }
}
