# Activity

Who is watching (Jellyfin, beefy), who is listening (Audiobookshelf, fastpi), what is downloading or waiting. Anonymous counts only: categories, no titles, no names.

- **URL:** https://activity.holy-grail.ch (Holy Grail SSO, groups `homelab-admins` and `homelab-users`; LAN/VPN now, internet after [Owner steps](#owner-steps))
- **Polls only while someone looks:** nothing (no Waker, no gate, no ABS, no qBittorrent) while nobody has the page open; see [Polling](#polling).
- **Never wakes beefy, never keeps it awake:** beefy is asked only while Beefy-Waker `/status` (never wakes) says `up`; the requests go to the read-only `activity-gate` on beefy, whose port is excluded from beefy's idle watcher.
- Rust, scratch image, uid 65060, read-only, no capabilities, 32 MB, no host port. Connections from addresses in neither `PAGE_ALLOW` nor `METRICS_ALLOW` are closed right after accept (no slot taken), so a neighbour on traefik_proxy cannot starve Traefik or the healthcheck. The page's Content-Security-Policy is set by the service: the one inline script and style allowed by their SHA-256 hashes (computed from the embedded page at start, `rust/src/csp.rs`), no `'unsafe-inline'`.

## Data flow

```
browser ─► Cloudflare/AdGuard ─► Traefik (authentik@file) ─► activity:8080  /  /api/state  (answers only Traefik 172.24.255.3)
Prometheus ─► activity_metrics (10.24.40.0/29) ─► activity:8080/metrics

activity, per poll:   traefik:8080/activity/waker/status ─► Waker 192.168.1.2:9001/status
                      Waker up? ─► GET traefik:8080/activity/gate/<contract paths> ─► gate 192.168.1.102:8095, side by side, one attempt each, 3 s timeout, Connection: close
                      Audiobookshelf audiobookshelf:8080 /api/sessions/open
                      traefik:8080/activity/qbit/api/v2/torrents/info?category=abr ─► qBittorrent 10.24.25.2:8080 (no login)
```

## Polling

| Situation | Polls |
|---|---|
| no `/api/state` within `VIEWER_SECONDS` (120) | none |
| first `/api/state` after that | one poll at once; that request and concurrent ones wait for it (max 4 s), then answer what is there |
| `/api/state` within the last 120 s | every `POLL_SECONDS` (30) |
| `/metrics`, `/health`, `/` (HTML) | never count as a viewer |

| Setting | Allowed |
|---|---|
| `POLL_SECONDS` | 1–86400 (0 is refused: it would poll beefy in a loop) |
| `VIEWER_SECONDS` | 1 s to a week |

The page fetches `/api/state` every 30 s only while its tab is visible (stops on `hidden`, fetches at once on `visible`); while beefy is up but its data is not live yet it asks again after 5 s (at most 3 times). It shows "updated HH:MM:SS" (the last poll) and "⚠️ beefy streams/downloads/data unavailable (gate not answering)" when the Waker says up but that part failed (`streams_failed`, `downloads_failed`); not in the first 90 s after a wake (`beefy_starting`: Jellyfin and the arrs start after sshd). The post-update checks read `/api/state`, so each run counts as a viewer for 2 min.

`/health` is 503 when the poll loop has stopped or a due poll has not run for 2 × `POLL_SECONDS` + 60 s (Docker marks the container unhealthy, autoheal restarts it).

### Internal routes (Traefik)

`../Traefik/traefik/dynamic/activity-internal.yml`: entry point `internal` (:8080, not published, not in the tunnel), host `traefik` (resolves only inside docker networks), no SSO. No firewall or gluetun rule for activity: Traefik forwards from the addresses already admitted.

| Router | Allows | Backend | Admitted because |
|---|---|---|---|
| `activity-waker` | GET `/activity/waker/status` | Waker 192.168.1.2:9001 | HOST-GUARD admits Traefik 172.24.255.3 |
| `activity-gate` | GET `/activity/gate/*` (the gate allow-lists the contract) | gate 192.168.1.102:8095 | beefy admits fastpi 192.168.1.2 (NAT source) |
| `activity-qbit` | GET `/activity/qbit/api/v2/torrents/info?category=abr`: every `category` value exactly `abr`, the other torrents/info parameters (filter, tag, sort, reverse, limit, offset, hashes, private, includeTrackers, include_trackers, includeFiles) refused | qBittorrent 10.24.25.2:8080 | gluetun admits Traefik 10.24.25.3; qBittorrent skips its login for it |

All three: `ipAllowList` 172.24.255.10 (activity, pinned) only; everyone else 403 (`activity.internal-only`); no access-log lines (`observability.accessLogs: false`, ~850 lines/h of disk log while the page is viewed). Traefik cannot match the raw query string, so `category=abr&category=abr` still passes (harmless); an unknown parameter is ignored by qBittorrent. Route test in a real Traefik: `bash tests/traefik/run.sh` (`activity.qbit-rule` checks the rule text).

`activity-gate` has no `healthCheck` (Traefik would poll beefy regardless of the Waker) and `serversTransport` `activity-gate-no-idle` (`idleConnTimeout: 1s`, `responseHeaderTimeout: 5s`), so Traefik holds no idle connection to beefy even if the gate's `keepalive_timeout 0` went away, and gives up on an unanswered request after 5 s (`activity.gate-transport`). The service's own client closes its connection at its 3 s timeout.

Audiobook downloads: the Audiobook-Requests importer has no download counts, so qBittorrent is read directly, through the route, limited to the one read.

Answers are parsed into typed fields and grouped at once; raw answers, titles and names are never stored, logged or served. Log lines name only the path and the error (`HTTP 503`, `timed out`).

## Staleness rule

Streams (Jellyfin sessions) and downloads (queues + request state) are stored separately: a failed queue keeps the streams live, and the other way round. A part counts as fresh when taken 0–90 s ago (a time in the future, after a clock step, is never fresh).

| Waker (`beefy`) | part fresh | Watching | Downloads |
|---|---|---|---|
| up | < 90 s | live | live |
| up | ≥ 90 s or none | ❔ unavailable | last known, "as of HH:MM" |
| asleep (`up: false`, phase idle) | any | 💤 nobody watching | last known, "as of …" |
| waking (phase waking, retrying, power_cycle) | any | ⏳ nobody watching yet | last known, "as of …" |
| broken (the wake failed) | any | ⚠️ unknown | last known, "as of …" |
| unknown | any | ❔ unavailable ("beefy state unknown") | last known, "as of …" |

"as of" shows the time today, "yesterday HH:MM", else weekday and date.

The last downloads are kept in the volume `activity_data` (`/data/last.json`, `{"v":2,"downloads":{…}}`; a version-1 file is read once; written when the downloads change, else every 10 min, and when the clock went back), so "as of" survives a restart.

## Categories

| Field | Values |
|---|---|
| kind | by the Jellyfin item type: `Movie`, `Episode` (series), `Anime`, `Music` (Audio), `Audiobook` (AudioBook), `Live TV` (TvChannel, LiveTvChannel, Program, LiveTvProgram), `Other` (music videos, trailers, …); quality only when a video stream is known |
| quality | `4K HDR`, `4K SDR`, `1080p HDR`, `1080p SDR`, `720p`, `SD`: height ≥ 2000 or width ≥ 3800 → 4K, ≥ 1000 / 1900 → 1080p, ≥ 700 / 1260 → 720p (width catches letterboxed films); HDR = VideoRangeType HDR10/HDR10+/DOVI*/HLG; queue items: Radarr/Sonarr resolution, HDR from the custom format names (HDR, DV, Dolby Vision, HLG); waiting requests have no quality yet |
| mode | `direct play`, `direct stream`, `transcode`, `transcode (audio)` (Transcode with `IsVideoDirect`) |
| state | `downloading`, `importing`, `queued`, `stalled`, `paused`, `waiting for night`, `waiting for release`, `problem` |

| Source | Rule |
|---|---|
| Jellyfin sessions | only sessions with a playing item; paused = `PlayState.IsPaused` |
| Anime | Sonarr `seriesType == "anime"`: queue items by their series, playing episodes by series name or series folder in the item path, requests by tmdb id; unknown → `Episode` |
| Queue state | see the table below; a title with several records shows the highest: problem > stalled > importing > downloading > queued > paused > waiting for night |
| Night window | `night-waiting.json` `low_tariff` → `night_open` (22:00–06:00 and Sundays, night-downloads.py on beefy); the page shows "from 22:05" (fastpi's night-download wake of beefy) while closed |
| Requests | `request-state.json`: `unreleased` + `noRelease` → waiting for release; `canWait` → waiting for night; titles already in its `queue` are counted from the arr queues |
| Series counts | queue: distinct series, seasons, episode records; waiting for night: missing episodes of the monitored seasons (specials skipped) |
| Listening | ABS open sessions (and share sessions) synced within 5 min (ABS keeps stale sessions open 36 h) |
| Audiobook downloads | qBittorrent category `abr`: downloading = downloading, stalledDL, metaDL, forcedDL, forcedMetaDL, allocating, checkingDL, moving, checkingResumeData; queued = queuedDL; paused = stoppedDL, pausedDL; problem = error, missingFiles; seeding and finished ones are not counted |

Radarr/Sonarr v3 queue records (`trackedDownloadState`, `trackedDownloadStatus`, `status` from the download client), first match wins:

| Record | State |
|---|---|
| tracked state `imported` or `ignored` | not shown (done) |
| tracked state importBlocked, failedPending, failed; tracked status `error`; status `failed` | problem |
| tracked state importPending, importing; status `completed` | importing |
| status `paused`, download id in `night-waiting.json` | waiting for night |
| status `paused`, otherwise (paused by hand) | paused |
| status `queued` (client queue) or `delay` (delay profile) | queued |
| status `warning` (e.g. stalled, no connections) or `downloadClientUnavailable`; tracked status `warning` | stalled |
| anything else | downloading |

Gaps are flagged in `downloads_gaps` and named under Downloads: `truncated` (a queue reports more records than its page: `pageSize` 200 Radarr / 500 Sonarr, fixed by the gate contract), `series_unavailable` (no anime, no season counts; also `streams_series_unavailable` for the streams), `night_unavailable` (night-held items show as paused). Each also gets one log line per change ("beefy poll incomplete: …").

## Gate path contract

The gate on beefy (`activity-gate`, port 8095; 8097 is jellyfin-popular) allow-lists exactly these GET paths (query strings included) and injects the API keys; fastpi holds none. Source of truth: `rust/src/beefy.rs` (`PATH_*`).

| Path on the gate | Upstream | Needed |
|---|---|---|
| `/jellyfin/Sessions?ActiveWithinSeconds=60` | Jellyfin `/Sessions` | yes |
| `/seerr/request-state.json` | Seerr bar `/srv/appdata/indexer-bar/request-state.json` | yes |
| `/seerr/night-waiting.json` | Seerr bar `/srv/appdata/indexer-bar/night-waiting.json` | no (night-held items show as paused, flagged) |
| `/radarr/api/v3/queue?pageSize=200&includeMovie=true` | Radarr | yes |
| `/sonarr/api/v3/queue?pageSize=500&includeSeries=true&includeEpisode=true` | Sonarr | yes |
| `/sonarr/api/v3/series` | Sonarr, only when an episode plays or a series request waits | no (no anime, no series counts, flagged) |

Paths are asked side by side (the series list after the others, only when needed). Per poll: the Waker once, then one request per path.

| Path | Read |
|---|---|
| `/sonarr/api/v3/series` (the largest answer, ~100 KB) | only when needed, then kept as an index (anime titles and folders as keyed hashes, ids, missing counts; no titles) and read again after 30 min, or once when the Sonarr queue or a request names a series the index does not know |
| `/seerr/request-state.json` (~17 KB) | conditional: `If-None-Match` with the last ETag (nginx serves it as a static file); a 304 reuses the cached copy | Sessions failing = no new streams for that tick; request state or a queue failing = no new downloads for that tick (the last ones stay, "as of"). One log line per change names the failed paths.

## Secrets

| File | Owner, mode | What |
|---|---|---|
| `secrets/abs_api_key` | 65060, 0400 | copy of `../Audiobook-Requests/secrets/abs_api_key` (ABS key `audiobook-importer`; `/api/sessions/open` needs admin) |

Rotation: `sudo install -o 65060 -g 65060 -m 0400 <new file> secrets/<name>`; read on every use, no restart.

## Owner steps

Authentik application `Activity` (groups `homelab-admins`, `homelab-users`, `../Authentik/scripts/provision-admin-sso.py` §10) is live. Left: the public hostname (the tunnel's routes are dashboard-managed; no API token for them).

| # | What | How | Check |
|---|---|---|---|
| 1 | Cloudflare public hostname | Zero Trust → Networks → Tunnels → `fastpi` → Public Hostname (published application routes) → Add: subdomain `activity`, domain `holy-grail.ch`, service `HTTPS` `192.168.1.2:443`, TLS → No TLS Verify on (as `specs`, `wiki`) | `curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://activity.holy-grail.ch/` from outside → `302 https://sso.holy-grail.ch/…` |
| 2 | WAN probe | add `https://activity.holy-grail.ch/` to job `blackbox-wan-gated` in `../grafana/prometheus/prometheus.yml`, `SERVICES=prometheus ../_global/scripts/update-project.sh Docker/grafana recreate` | `probe_success{job="blackbox-wan-gated",instance="https://activity.holy-grail.ch/"}` = 1 |

LAN and VPN work already (AdGuard wildcard; LAN probe in `blackbox-gated`).

## Operations

| What | Command |
|---|---|
| Build + deploy | `flock ~/.cache/claude-work/rust-build.lock Docker/_global/scripts/update-project.sh Docker/Activity build` (cargo test runs in the build) |
| Black-box suite (fakes for Waker, gate, ABS, qBittorrent; ~1 min) | `bash tests/blackbox/run.sh` (binary from `activity:local`), `run.sh image IMAGE`, `run.sh bin BINARY` |
| Page tests (headless Chromium, `/api/state` from fixtures; Playwright from `PLAYWRIGHT`, global, or `~/Documents/development/LoyaltyCards`) | `node --test tests/page/page.test.cjs` |
| Customization checks | `Docker/_global/scripts/post-update-check.sh Activity` |
| State | `docker exec traefik wget -qO- http://activity:8080/api/state` |
| Rollback | `update-project.sh` rolls back on a failed check; remove: `docker compose down` here, delete `../Traefik/traefik/dynamic/activity.yml` and `activity-internal.yml`, the `activity` job and network in `../grafana` |

## Metrics

Last-known values (from the last poll, `activity_last_poll_timestamp_seconds`; nothing is refreshed while nobody views): `activity_viewer_active` (1 = page viewed within 120 s, polling), `activity_beefy_up` (1/0, absent = unknown), `activity_beefy_snapshot_age_seconds`, `activity_watching_streams`, `activity_streams{kind,quality,mode}`, `activity_downloads{state,kind,quality}` (titles), `quality="unknown"` = no quality known (waiting requests, a stream or queue item without resolution), `activity_listening_sessions`, `activity_audiobook_downloads{state}` (downloading, queued, paused, problem). Job `activity` in `../grafana/prometheus/prometheus.yml`.

No alerts on these: without a viewer the data is stale by design, and with one the page shows the failure itself. The service down is `TargetDown`/`ContainerDown`; broken routes show in the post-update checks (`activity.waker-route`, `activity.qbit-route`).
