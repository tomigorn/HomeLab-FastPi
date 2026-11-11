# Activity

Who is watching (Jellyfin, beefy), who is listening (Audiobookshelf, fastpi), what is downloading or waiting. Anonymous counts only: categories, no titles, no names.

- **URL:** https://activity.holy-grail.ch (Holy Grail SSO, group `homelab-admins`; see [Owner steps](#owner-steps))
- **Never wakes beefy, never keeps it awake:** beefy is asked only while Beefy-Waker `/status` (never wakes) says `up`; the requests go to the read-only `activity-gate` on beefy, whose port is excluded from beefy's idle watcher. A page view never causes a request to beefy: the page reads the service's memory.
- Rust, scratch image, uid 65060, read-only, no capabilities, 32 MB, no host port.

## Data flow

```
browser ─► Cloudflare/AdGuard ─► Traefik (authentik@file) ─► activity:8080  /  /api/state  (answers only Traefik 172.24.255.3)
Prometheus ─► activity_metrics (10.24.40.0/29) ─► activity:8080/metrics

activity, every 15 s: Waker http://192.168.1.2:9001/status
activity, every 30 s: Waker up? ─► GET gate http://192.168.1.102:8097/<contract paths>, one attempt each, 3 s timeout, Connection: close
                      Audiobookshelf audiobookshelf:8080 /api/sessions/open
                      qBittorrent 10.24.25.2:8080 /api/v2/torrents/info?category=abr
```

Answers are parsed into typed fields and grouped at once; raw answers, titles and names are never stored, logged or served. Log lines name only the path and the error (`HTTP 503`, `timed out`).

## Staleness rule

| Waker | last good poll | Watching | Downloads |
|---|---|---|---|
| up | < 90 s | live | live |
| up | ≥ 90 s or none | ❔ unavailable | last known, "as of HH:MM" |
| asleep | any | 💤 nobody watching | last known, "as of HH:MM" |
| unknown | any | ❔ unavailable ("beefy state unknown") | last known, "as of HH:MM" |

The last snapshot is kept in the volume `activity_data` (`/data/last.json`, written when the downloads change, else every 10 min), so "as of" survives a restart.

## Categories

| Field | Values |
|---|---|
| kind | `Movie`, `Episode` (series), `Anime`, `Other` (no video stream: music, audiobooks in Jellyfin) |
| quality | `4K HDR`, `4K SDR`, `1080p HDR`, `1080p SDR`, `720p`, `SD`: height ≥ 2000 or width ≥ 3800 → 4K, ≥ 1000 / 1900 → 1080p, ≥ 700 / 1260 → 720p (width catches letterboxed films); HDR = VideoRangeType HDR10/HDR10+/DOVI*/HLG; queue items: Radarr/Sonarr resolution, HDR from the custom format names (HDR, DV, Dolby Vision, HLG); waiting requests have no quality yet |
| mode | `direct play`, `direct stream`, `transcode`, `transcode (audio)` (Transcode with `IsVideoDirect`) |
| state | `downloading`, `importing`, `waiting for night`, `waiting for release`, `problem` |

| Source | Rule |
|---|---|
| Jellyfin sessions | only sessions with a playing item; paused = `PlayState.IsPaused` |
| Anime | Sonarr `seriesType == "anime"`: queue items by their series, playing episodes by series name or series folder in the item path, requests by tmdb id; unknown → `Episode` |
| Queue state | as `night-downloads.py`: import blocked/failed → problem > importPending/importing → importing > paused and download id in `night-waiting.json` → waiting for night > downloading |
| Requests | `request-state.json`: `unreleased` + `noRelease` → waiting for release; `canWait` → waiting for night; titles already in its `queue` are counted from the arr queues |
| Series counts | queue: distinct series, seasons, episode records; waiting for night: missing episodes of the monitored seasons (specials skipped) |
| Listening | ABS open sessions (and share sessions) synced within 5 min (ABS keeps stale sessions open 36 h) |
| Audiobook downloads | qBittorrent category `abr`: downloading = downloading, stalledDL, metaDL, forcedDL, forcedMetaDL, allocating, checkingDL; queued = queuedDL |

## Gate path contract

The gate on beefy (`activity-gate`, port 8097) allow-lists exactly these GET paths (query strings included) and injects the API keys; fastpi holds none. Source of truth: `rust/src/beefy.rs` (`PATH_*`).

| Path on the gate | Upstream | Needed |
|---|---|---|
| `/jellyfin/Sessions?ActiveWithinSeconds=60` | Jellyfin `/Sessions` | yes |
| `/seerr/request-state.json` | Seerr bar `/srv/appdata/indexer-bar/request-state.json` | yes |
| `/seerr/night-waiting.json` | Seerr bar `/srv/appdata/indexer-bar/night-waiting.json` | no (paused items count as downloading) |
| `/radarr/api/v3/queue?pageSize=200&includeMovie=true` | Radarr | yes |
| `/sonarr/api/v3/queue?pageSize=500&includeSeries=true&includeEpisode=true` | Sonarr | yes |
| `/sonarr/api/v3/series` | Sonarr, only when an episode plays or a series request waits | no (no anime, no series counts) |

A needed path failing = no new snapshot for that tick.

## Secrets

| File | Owner, mode | What |
|---|---|---|
| `secrets/abs_api_key` | 65060, 0400 | copy of `../Audiobook-Requests/secrets/abs_api_key` (ABS key `audiobook-importer`; `/api/sessions/open` needs admin) |
| `secrets/qbit_pass` | 65060, 0400 | copy of `../mouse/secrets/qbit_pass` |

Rotation: `sudo install -o 65060 -g 65060 -m 0400 <new file> secrets/<name>`; read on every use, no restart.

## Owner steps

Open until done; the page works without them, beefy and the audiobook downloads then show "unavailable".

| # | What | How | Check |
|---|---|---|---|
| 1 | Authentik application, group `homelab-admins` (until then the outpost knows no provider for this host: 404, nothing gets through) | add to `../Authentik/scripts/provision-admin-sso.py`: `app_for("activity", "Activity", proxy("activity-proxy", "https://activity.holy-grail.ch"), "https://activity.holy-grail.ch")`, then `cd ../Authentik && docker compose exec -T server ak shell < scripts/provision-admin-sso.py \| python3 scripts/apply-sso-env.py` | `post-update-check.sh Activity`: `activity.page-sso` → `302 https://sso…` |
| 2 | Waker reachable (HOST-GUARD) | `../_global/scripts/host-input-guard.sh`: `ACTIVITY=172.24.255.10/32` and `iptables -A HOST-GUARD -s "$ACTIVITY" -p tcp --dport 9001 -j RETURN` before the LOG line; `sudo ../_global/scripts/host-input-guard.sh --persist`; then `WAKER_URL=http://192.168.1.2:9001` in `.env` + `.env.example`, `../_global/scripts/update-project.sh Docker/Activity recreate` | `/api/state` → `"beefy":"up"` or `"asleep"` |
| 3 | Gate reachable (DOCKER-USER) | `../_global/scripts/docker-user-lan-guard.sh`: `ACTIVITY=172.24.255.10/32` and `iptables -A DOCKER-USER -s "$ACTIVITY" -o "$IFACE" -d "$BEEFY" -p tcp --dport 8097 -j RETURN` before the LAN DROP; `sudo ../_global/scripts/docker-user-lan-guard.sh --persist` | with beefy awake and the gate built: `"beefy_data":"live"` |
| 4 | qBittorrent reachable (gluetun) | `../mouse/gluetun/post-rules.txt`: `iptables -I INPUT 1 -d 10.24.25.2 -s 10.24.25.7 -p tcp --dport 8080 -j ACCEPT`; `docker restart gluetun_mouse` | `audiobook_downloads` not null |
| 5 | Public hostname | Cloudflare Tunnel: `activity.holy-grail.ch` → `https://192.168.1.2:443`, No TLS Verify (LAN and VPN work already: AdGuard wildcard) | `dig +short activity.holy-grail.ch @1.1.1.1` |
| 6 | Gate on beefy | beefy repo, plan task 5 (paths above) | step 3 check |

Until step 2 `WAKER_URL=off`: the dropped probes would use up HOST-GUARD's shared drop-log budget (6/min).

## Operations

| What | Command |
|---|---|
| Build + deploy | `flock ~/.cache/claude-work/rust-build.lock Docker/_global/scripts/update-project.sh Docker/Activity build` (cargo test runs in the build) |
| Black-box suite (fakes for Waker, gate, ABS, qBittorrent; ~1 min) | `bash tests/blackbox/run.sh` (binary from `activity:local`), `run.sh image IMAGE`, `run.sh bin BINARY` |
| Customization checks | `Docker/_global/scripts/post-update-check.sh Activity` |
| State | `docker exec traefik wget -qO- http://activity:8080/api/state` |
| Rollback | `update-project.sh` rolls back on a failed check; remove: `docker compose down` here, delete `../Traefik/traefik/dynamic/activity.yml`, the `activity` job and network in `../grafana` |

## Metrics

`activity_beefy_up` (1/0, absent = unknown), `activity_beefy_snapshot_age_seconds`, `activity_watching_streams`, `activity_streams{kind,quality,mode}`, `activity_downloads{state,kind,quality}` (titles), `activity_listening_sessions`, `activity_audiobook_downloads{state}`. Job `activity` in `../grafana/prometheus/prometheus.yml`.
