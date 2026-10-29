# CrowdSec

Reads Traefik's access log, bans attackers; the Traefik bouncer plugin
(`Traefik/traefik/dynamic/crowdsec.yml`) enforces the bans on every public route.
Also pulls the free **community blocklist** (CAPI, ~18k IPs, every 2 h) and shares
its own detections back, which is CrowdSec's default. Not enrolled in the
CrowdSec Console (proprietary SaaS); everything on the dashboard is local.

## What happens when CrowdSec is down (bouncer failure behaviour)

**The edge fails OPEN on a stale ban list**, by design (2026-10-19):

| | `live` mode (before 2026-10-19) | `stream` + `updateMaxFailure: -1` (now) |
|---|---|---|
| LAPI unreachable | every uncached visitor gets **403** (plugin treats a failed lookup as "banned") | last known ban list stays enforced, everyone else passes |
| CrowdSec restart / update | public sites down for the restart | no visible effect |
| New ban reaches Traefik | immediately (per-request lookup, 60 s clean-cache) | within 60 s (`updateIntervalSeconds`) |

Verified both ways: code read (`bouncer.go`, `handleNoStreamCache` returns
`BannedValue` on any LAPI error; `updateMaxFailure` is only consulted in
stream/alone mode), and a live test with CrowdSec stopped for 75 s: clean IP 200,
locally banned IP 403, community-blocklist IP 403, public route 200.

The cost is that new attacks are not banned while CrowdSec is down. The
`CrowdSecDown` alert (10 min) and `CrowdSecBouncerNotPulling` make that visible.
Trusted ranges (LAN, VPN, docker) bypass the bouncer entirely in both modes.

## Dashboard

**Grafana > fastpi > CrowdSec**: https://grafana.holy-grail.ch/d/crowdsec-overview
(Authentik group `homelab-admins`, LAN/VPN only, inherited from Grafana.)

**Counting unit: one attack = one CrowdSec alert**, meaning one IP tripping one
scenario (e.g. "probed 10 sensitive paths in seconds"). An attack is typically 5-50
requests. It is not a ban count (bans expire, attacks are history) and not a request
count ("Blocked" tiles count requests).

| Section | Answers | Source |
|---|---|---|
| Right now | blocked requests 24h/7d, active bans (mine vs community), attacks and attacker IPs 24h | exporter + `cs_active_decisions` |
| Status tiles | CrowdSec up, bouncer last sync, last CAPI pull, % log lines parsed, version, auto-update result, hub age, exporter age | exporter + engine |
| Threat data | bans by origin, hub last changed / last checked, GeoIP data age, extra blocklists (see "Threat data refresh"), bouncer plugin installed / latest (red = outdated or Traefik not restarted) | exporter + auto-update + engine |
| Blocked traffic | bouncer drops per hour vs all Traefik 403s; responses by status class | exporter + Traefik |
| Where attacks come from | **map** + table for the selected time range, top-10 countries over time, **lifetime per country**, top 20 IPs (24h) | exporter |
| What attackers are doing | top scenarios 24h / selected range / lifetime, attacks per hour by scenario, bans by origin | exporter + engine |
| Engine health | log lines read/parsed/unparsed/whitelisted, bouncer syncs, LAPI p95 latency, memory | engine (`crowdsec:6060`) |

Data paths:
- **Engine metrics:** `crowdsec:6060` (docker network `crowdsec` only) -> Prometheus job `crowdsec` (30 s).
- **Exporter** `scripts/crowdsec_exporter.py`, every 5 min (`crowdsec-exporter.timer`):
  `cscli ... -o json` -> `/var/lib/node-exporter/textfile/crowdsec.prom` -> node-exporter
  -> Prometheus. It fills what the engine does not export:
  - `crowdsec_attacks_by_country_total{country,country_name}` and
    `crowdsec_attacks_by_scenario_total{scenario}`: **monotonic counters** kept in
    `/var/lib/crowdsec-exporter/state.json`. They survive CrowdSec restarts and
    CrowdSec's own 7-day / 5000-alert flush. They are de-duplicated by alert UUID, so a DB
    restore (rollback) cannot double-count. Every country (~250) and installed
    scenario (~55) is published, at 0 if never seen, because `increase()` cannot see
    a series that is born at 1. Manual (`cscli`), community-list and simulated
    alerts are excluded.
  - `crowdsec_attacks_recent{window}`, `crowdsec_attackers_recent{window}`,
    `crowdsec_attacks_24h_by_scenario`, `crowdsec_top_attacker_attacks_24h{ip,country,as_name,scenario}`
    (top 20). Trailing windows straight from CrowdSec's DB, so they don't depend on
    Prometheus history.
  - `crowdsec_bouncer_dropped_requests_total`: the bouncer's own exact drop count.
    The plugin (v1.8.1) reports remediation usage metrics to the LAPI every 10 min,
    and they were otherwise only visible in `cscli metrics show bouncers`. Made
    monotonic across LAPI metric flushes.
  - `crowdsec_bouncer_last_pull_timestamp_seconds`, `crowdsec_capi_last_pull_timestamp_seconds`
    (newest `update : +N/-M IPs` alert of kind `capi`), `crowdsec_hub_index_timestamp_seconds`,
    `crowdsec_hub_items_not_ok`, and `crowdsec_exporter_*` in a separate status file.
  - `crowdsec_bouncer_plugin_*` / `crowdsec_bouncer_reported_version_mismatch`: see
    "Updating the bouncer plugin".
  - Geo data is CrowdSec's own GeoIP enrichment (`source.cn`, `as_name`); the
    map draws Grafana's bundled `public/maps/countries.geojson`, with no tile server, so
    nothing about viewers or attackers leaves the server.

**History:** Prometheus keeps 400 days (capped at 60 GB, about 35 GB/year
measured). The per-country/per-scenario counters were seeded on 2026-10-19 from
every alert still in CrowdSec's DB (oldest 2026-10-11, 748 attacks), and
the same history was back-filled into Prometheus as 5-minute samples (promtool
`create-blocks-from openmetrics`). So time-range views work from 2026-10-11 on. The
"lifetime" panels are the raw counters and stay correct even beyond retention.

Cardinality: about 350 series from the exporter, which is negligible next to the ~9k in Prometheus.

## Auto-update

`scripts/crowdsec-autoupdate.sh`, daily at **05:07** (±10 min, `crowdsec-autoupdate.timer`, `Persistent=true`):

1. Reads the newest **stable** release (GitHub `/releases/latest`, which skips `-rc`) and
   checks the tag exists on Docker Hub.
   - **patch/minor:** installed.
   - **new major:** not installed. It reports `major_available` and waits for a human
     (read release notes, check plugin compatibility).
2. **Update:** pull while still running -> stop -> tar both volumes to
   `~/backups/pre-update/<date>/crowdsec-autoupdate/` (owner-only 0700/0600, tar runs in a digest-pinned alpine; stopped, so the SQLite DB is
   consistent) -> set `CROWDSEC_TAG` in `.env` -> start. Downtime ~15 s, invisible
   thanks to the fail-open bouncer.
3. **Verify:** container running with 0 restarts, `cscli lapi status` OK, bouncer pulled
   after the restart, a test ban on 203.0.113.250 (TEST-NET) returns 403 through
   Traefik, a clean TEST-NET IP is not refused, and the public route is not 404/5xx/000.
4. **Rollback** if any check fails: old tag back in `.env`, old image id re-tagged,
   **volumes restored from the backup just taken** (a new version may migrate the DB
   forward only), recreate, verify again. The version goes to
   `/var/lib/crowdsec-autoupdate/bad_versions` and is skipped (`held_back`) until a
   newer release appears.
5. **No new release:** `cscli hub update` + `cscli hub upgrade`. If any item version or
   data file changed: SIGHUP reload (~3 s), verify; a restart if the reload misbehaves.
   The image itself only refreshes hub content at container start (no cron runs in
   it), so this daily step is what keeps parsers and scenarios current.
6. **Report:** `crowdsec_autoupdate_result{result,from,to}` to the textfile collector, then
   `grafana/prometheus/rules/crowdsec.yml` -> Alertmanager:
   - `updated` / `hub_updated` -> Telegram (info)
   - `rolled_back` -> email + Telegram (warning)
   - `rollback_failed` -> critical
   - `held_back` / `major_available` / `error` for 36 h / no run for 3 days -> Telegram

After an image update `.env.example` is bumped too. **Commit it**
(`CrowdSec: update to vX.Y.Z`); the script deliberately never commits.

```bash
# pause (keeps reporting "paused"):  set CROWDSEC_AUTOUPDATE=off in .env
# or stop it entirely:               sudo systemctl disable --now crowdsec-autoupdate.timer
sudo systemctl start crowdsec-autoupdate.service    # run now
journalctl -u crowdsec-autoupdate -n 50             # what it did
DRY_RUN=1 scripts/crowdsec-autoupdate.sh            # decide only, change nothing
TEST_FORCE_FAIL=1 scripts/crowdsec-autoupdate.sh    # rollback drill (first check fails)
```

Tested 2026-10-19 end to end on real images: v1.8.0 -> v1.8.1 update (verified), a
forced-failure drill (rolled back to v1.8.0 with restored volumes, verified,
`held_back` on the next run), then a clean update back to v1.8.1. The `updated`
notification arrived in Telegram.

**Not covered:** the Traefik bouncer plugin. It is vendored as a local plugin
(`Traefik/traefik/plugins-local/`, see `Traefik/traefik/traefik.yml` for why) and
updating it is a Traefik static change, so it stays manual, but it is **monitored**
(next section) so updating one side never silently leaves the other behind.

## Updating the bouncer plugin

The exporter (every 5 min) reads the vendored `version.go`, the newest upstream
release (GitHub `/releases/latest`, cached 6 h in `/var/lib/crowdsec-exporter/plugin_latest.json`,
a failed check keeps the last answer) and the version the running bouncer reports to
the LAPI (`cscli bouncers list`, newest `last_pull` wins because Traefik re-registers as
`traefik-bouncer@<ip>` after each restart and old entries linger):

| Metric | Meaning |
|---|---|
| `crowdsec_bouncer_plugin_version_info{installed,latest,reported}` | the three versions as labels (dashboard tile "Bouncer plugin") |
| `crowdsec_bouncer_plugin_outdated` | 1 = upstream has a newer release (absent while upstream is unknown: no false alarm) |
| `crowdsec_bouncer_reported_version_mismatch` | 1 = Traefik runs another version than the files, or no bouncer has pulled |
| `crowdsec_bouncer_plugin_latest_checked_timestamp_seconds` | last successful GitHub check |

| Alert | When | Where |
|---|---|---|
| `CrowdSecBouncerPluginOutdated` | outdated for 1 d (a release gets a day of soak time) | warning: email + Telegram, repeated every 12 h until updated |
| `CrowdSecBouncerPluginMismatch` | mismatch for 15 min (files replaced, Traefik not restarted; or a restart kept the old build) | warning: email + Telegram |
| `CrowdSecBouncerPluginCheckStale` | no successful GitHub check for 3 days | info: Telegram |

Both warnings resolve themselves (one RESOLVED message) once `reported` = `installed` =
`latest`. Cup only tracks container images (`images.extra` takes image references, not
files or releases), so the Prometheus path above is the only monitoring; the plugin does
not appear in Cup.

The plugin states no CrowdSec minimum/maximum, only feature gates (AppSec needs plugin
>= 1.2.0 + CrowdSec >= 1.6.0, AppSec bot detection plugin >= 1.8.0 + CrowdSec >= 1.8.0),
so there is no compatibility alert. `CrowdSecMajorUpdateAvailable` is the moment to
read the plugin's release notes.

```bash
V=v1.9.0   # the tag the alert names
cd /home/pi/Projects/Docker/Traefik/traefik/plugins-local/src/github.com/maxlerebourg
curl -fsSL "https://github.com/maxlerebourg/crowdsec-bouncer-traefik-plugin/archive/refs/tags/$V.tar.gz" | tar xz
rm -rf crowdsec-bouncer-traefik-plugin && mv "crowdsec-bouncer-traefik-plugin-${V#v}" crowdsec-bouncer-traefik-plugin
grep pluginVersion crowdsec-bouncer-traefik-plugin/version.go          # must say $V
diff <(git show HEAD:Docker/Traefik/traefik/plugins-local/src/github.com/maxlerebourg/crowdsec-bouncer-traefik-plugin/README.md) crowdsec-bouncer-traefik-plugin/README.md | grep -i -E "crowdsec [0-9]|breaking|renamed" # config keys, CrowdSec requirements
docker restart traefik && sleep 90 && docker logs --since 2m traefik 2>&1 | grep -i -E "error|crowdsec"   # fails closed: must be clean
docker exec crowdsec cscli bouncers list                                 # newest traefik-bouncer@<ip> reports $V
sudo systemctl start crowdsec-exporter.service && grep bouncer_plugin /var/lib/node-exporter/textfile/crowdsec.prom
Docker/_global/scripts/smoke-test.sh                                     # "bouncer plugin current + running  0 0"
git add -A Docker/Traefik/traefik/plugins-local && git commit -m "Traefik: update CrowdSec bouncer plugin to ${V#v}"
```

v1.8.1 is installed (updated 2026-10-19 from v1.7.1, same config keys; backup of the
old tree is a git revert away).

## Threat data refresh

"Updating CrowdSec" is five different things with five cadences. Checked end to end on
2026-10-19 (each row says how):

| Layer | What | Cadence | Source | How it was verified | Changed |
|---|---|---|---|---|---|
| Community blocklist (CAPI) | ~19k IPs seen attacking other CrowdSec users; this server's detections are shared back | **every 2 h** (hardcoded `pullIntervalDefault = 2h` ±5 min in `pkg/apiserver/apic.go` v1.8.1; no config key or env var, only `online_client.pull.community: true/false`) | api.crowdsec.net | `cscli capi status` OK; `cscli alerts list --origin CAPI` shows `update : +15000/-0 IPs` every 2 h; a CAPI IP returns 403 through Traefik | nothing to tune; smoke checks + `CrowdSecCommunityBlocklistStale` (8 h) |
| Hub content (parsers, scenarios, collections, appsec rules) | the detection rules | **daily 05:07**: `cscli hub update && cscli hub upgrade`, SIGHUP reload if anything changed, then the same verification as an image update | hub.crowdsec.net | SIGHUP reload tested: parsers reloaded in ~3 s, LAPI OK, bouncer re-pulled 60 s later, CAPI IP still 403. Container start also refreshes the hub | dashboard tiles "Hub checked" / "Hub last changed" |
| Hub data files (GeoLite2 City/ASN for `geoip-enrich`, bad-user-agent and CVE lists) | enrichment and pattern data | **daily** with the hub upgrade: `cscli hub upgrade` always runs "check & update data files" (only `--force` re-downloads unconditionally) | hub-data.crowdsec.net | plan shown by `cscli hub upgrade --dry-run`; mtimes in `/var/lib/crowdsec/data` move when upstream publishes | exporter `crowdsec_data_file_timestamp_seconds{file}`, tile "GeoIP data age", alert `CrowdSecGeoIPStale` (60 d, info) |
| Bouncer sync | Traefik plugin pulls the decision stream | **every 60 s** (`updateIntervalSeconds`), fail-open | LAPI | `cscli bouncers list` last pull; active CAPI IPv4 + IPv6 403 (expired ones, still listed by `cscli` with a negative duration, rightly pass), clean TEST-NET IP 200 | smoke checks "community IPs blocked (403 403)", "clean IP passes (200)" |
| Allowlist `home` | the home WAN IP is never banned | static | LAPI DB | import of an allowlisted IP is refused (`cscli decisions import`), CAPI decisions are filtered in `ApplyApicWhitelists` | none |
| Program version | the engine image | daily 05:07, patch/minor, verified, rollback | GitHub releases + Docker Hub | see "Auto-update" | none |

**Additional (non-Console) blocklists: deliberately not imported.** Spamhaus DROP,
DShield and Firehol level1 are free for private use and low on false positives, and
`cscli decisions import --scope range` loads them fine (tried 2026-10-19 with
203.0.113.0/24). But the Traefik bouncer plugin in stream mode keys its cache by the
decision value and looks the client IP up by exact match (`handleStreamCache` /
`cacheClient.Get(remoteIP)`, v1.8.1 and upstream `main` alike), so a range
decision is never enforced: 203.0.113.250 kept getting 200 for 100 s with the /24
banned. Only live mode (LAPI matches ranges server-side) would enforce them, and live
mode fails closed, which is why it was abandoned. The CrowdSec Console blocklists
would be delivered as single IPs, but need enrollment (not wanted). If an extra list
is ever wanted: DShield's 20 /24s could be expanded to ~5k single IPs, but note the
plugin applies `Deleted` before `New` in one sync since v1.8.0, so a
delete-and-reimport cycle inside one 60 s window is safe. Dashboard tile
"Extra blocklists" shows "none configured" until something is imported.

## Install / files

```bash
./install.sh     # copies systemd/*.service|timer, enables both timers, runs the exporter once
python3 scripts/test_crowdsec_exporter.py
```

| File | Purpose |
|---|---|
| `scripts/crowdsec_exporter.py` | textfile exporter (5 min) |
| `scripts/crowdsec-autoupdate.sh` | daily update + hub upgrade, verify, rollback |
| `systemd/` | `crowdsec-exporter.{service,timer}`, `crowdsec-autoupdate.{service,timer}` |
| `/var/lib/crowdsec-exporter/state.json` | lifetime counters (back it up if you care about them) |
| `/var/lib/crowdsec-exporter/plugin_latest.json` | cached newest bouncer-plugin release (6 h) |
| `/var/lib/crowdsec-autoupdate/` | lock, `bad_versions`, `last_change` |

## Things that will bite

- **Bouncer 403s feed the 403 brute-force scenario.** While an IP is banned, the
  bouncer's 403s land in the access log, and `LePresidente/http-generic-403-bf` re-bans
  it every few minutes. On 2026-10-18 the home IP (84.226.182.197) got stuck this way:
  one `http-probing` ban from public-side testing, then seven 403-bf re-bans driven by
  the LanguageTool browser extension retrying. Lift with
  `docker exec crowdsec cscli decisions delete -i <ip>`.
- `cscli bouncers delete` prefix-matches (see the Traefik README).
- Stale `traefik-bouncer@<old ip>` entries (Traefik restarted or got a new IP): `docker exec crowdsec cscli bouncers prune -d 10m --force` removes every bouncer that has not pulled for 10 min; the live one pulls every minute. The exporter and alerts strip `@<ip>`, so nothing else changes.
- **Rotate the bouncer key:** `docker exec crowdsec cscli bouncers add traefik-bouncer -o raw` into `Traefik/traefik/secrets/crowdsec_lapi_key` (`printf %s`, keep `pi:65026 0640`), `docker restart traefik`, wait for the new `traefik-bouncer` to pull, test a ban, then `cscli bouncers prune -d 2m --force` drops the old key's `@<ip>` children (`bouncers delete` refuses auto-created children). Testing a key with curl from the host creates another `@172.24.0.1` child; prune it too.
- `cs_papi_last_pull_timestamp` is the Console **Polling** API and is always 0 without
  enrollment. Use `crowdsec_capi_last_pull_timestamp_seconds`.

## CLI

`docker exec crowdsec cscli alerts list`, `cscli decisions list`, `cscli metrics`,
`cscli capi status`, `cscli bouncers list`, `cscli hub list`.

## Home IP allowlist (2026-10-19)

The home WAN IP is in the CrowdSec allowlist `home`, so CrowdSec never bans it. Without this,
one ban caused a loop: the bouncer's 403s fed `LePresidente/http-generic-403-bf`, which banned
the IP again every few minutes (it happened 7 times on 2026-10-18, set off by the LanguageTool
browser extension retrying). The allowlist lives in CrowdSec's database, not in a file:

```bash
docker exec crowdsec cscli allowlists list
docker exec crowdsec cscli allowlists check <ip>
# if the ISP ever changes the home IP:
docker exec crowdsec cscli allowlists remove home <old-ip>
docker exec crowdsec cscli allowlists add home <new-ip> -d "home WAN IP"
```

The smoke test check "crowdsec home IP allowlisted" fails when the current home IP
(`lang-tool.ddns.net`) is no longer the allowlisted one.
