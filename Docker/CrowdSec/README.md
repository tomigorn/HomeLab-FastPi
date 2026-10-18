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
    The plugin (v1.7.1) reports remediation usage metrics to the LAPI every 10 min,
    and they were otherwise only visible in `cscli metrics show bouncers`. Made
    monotonic across LAPI metric flushes.
  - `crowdsec_bouncer_last_pull_timestamp_seconds`, `crowdsec_capi_last_pull_timestamp_seconds`
    (newest `update : +N/-M IPs` alert of kind `capi`), `crowdsec_hub_index_timestamp_seconds`,
    `crowdsec_hub_items_not_ok`, and `crowdsec_exporter_*` in a separate status file.
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
   `~/backups/pre-update/<date>/crowdsec-autoupdate/` (stopped, so the SQLite DB is
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
(`Traefik/traefik/plugins-local/`, see the Traefik README for why) and updating it
is a Traefik static change, so it stays manual. v1.7.1 is installed; v1.8.1 was
released on 2026-10-18.

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
| `/var/lib/crowdsec-autoupdate/` | lock, `bad_versions`, `last_change` |

## Things that will bite

- **Bouncer 403s feed the 403 brute-force scenario.** While an IP is banned, the
  bouncer's 403s land in the access log, and `LePresidente/http-generic-403-bf` re-bans
  it every few minutes. On 2026-10-18 the home IP (84.226.182.197) got stuck this way:
  one `http-probing` ban from public-side testing, then seven 403-bf re-bans driven by
  the LanguageTool browser extension retrying. Lift with
  `docker exec crowdsec cscli decisions delete -i <ip>`.
- `cscli bouncers delete` prefix-matches (see the Traefik README).
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
