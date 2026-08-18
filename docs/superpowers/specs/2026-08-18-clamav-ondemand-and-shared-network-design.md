# clamav on-demand scanning + HA/InfluxDB shared network

**Date:** 2026-08-18
**Status:** Design approved, ready for planning

Two independent changes requested together.

---

## Part A — clamav: resident daemon → event-driven watch-and-scan

### Problem
`clamav` runs a resident `clamd` daemon (antivirus project, `Docker/antivirus/`) that keeps the ~1 GB signature database loaded in RAM 24/7 (observed ~950 MB). Nothing queries it — no service, script, or download hook connects to clamd on port 3310 (verified by searching all projects). Scans are only ever manual. So ~950 MB is held constantly for a daemon that is "usually not needed/working" (user's words). A smaller `mem_limit` is NOT a fix: clamd needs the DB in RAM, so a lower cap makes it crash, and `autoheal-antivirus` would restart-loop it.

### Requirement (from user)
Scan each completed download **when it completes, before it is moved to the library** — and do not hold RAM when idle.

### Current pipeline (verified)
- sabnzbd (VPN-isolated, shares `gluetun` netns) writes finished jobs into `/mnt/seagate-red/sabnzbd/config/Downloads/complete/` (mounted `/scan/sabnzbd`).
- qbittorrent (VPN-isolated, shares `gluetun_mouse`) writes finished torrents into `/mnt/seagate-red/qbittorrent/downloads/complete/` (mounted `/scan/qbittorrent`).
- No *arr / automated mover exists. The user **manually** moves good items from `complete/` to `/mnt/seagate-black/library/{audiobooks,podcasts}` via Samba.

Because the downloaders are sealed in VPN namespaces and the library move is manual, a live in-downloader hook is the wrong tool. Watching the `complete/` folders catches the exact "download completed" moment (an atomic move into `complete/`) and runs before any manual library move.

### Design
Repurpose the `clamav` container:
- **Watcher:** `inotifywait -m -r -e close_write -e moved_to` on `/scan/sabnzbd/complete` and `/scan/qbittorrent/complete`. On each event, debounce briefly, then run a one-shot `clamscan -r -i --move=/scan/quarantine <path>`.
- **On-demand only:** `clamscan` loads the DB, scans, exits — RAM released. No resident `clamd`.
- **Definitions:** keep `freshclam --daemon` for periodic DB updates (light; does not hold the scan DB resident like clamd).
- **On detection:** `--move` relocates the infected file to a quarantine folder; the event is logged loudly. Nothing is deleted. Clean files are left in place.
- **Idle footprint:** ~5 MB (inotifywait) + freshclam — down from ~950 MB.

### Component changes (`Docker/antivirus/`)
- `clamav/Dockerfile`: add `inotify-tools`; drop the clamd-only bits (`clamav-daemon`, `clamav-clamdscan`, `netcat-openbsd`) and the `clamd.conf` COPY; keep `clamav` (provides `clamscan`), `clamav-libs`, `freshclam`. Replace the clamd PONG `HEALTHCHECK` with a watcher liveness check (`pgrep inotifywait`). Drop `EXPOSE 3310`.
- `clamav/entrypoint.sh`: new watch-and-scan loop (initial freshclam if DB missing → freshclam daemon → inotifywait loop → clamscan per event).
- `clamav/clamd.conf`: removed (clamscan does not need it).
- `docker-compose.yaml` (clamav service): remove `ports: 3310`; change the two `/scan/*` mounts from `:ro` to read-write (needed so `--move` can remove infected files from `complete/`); add a quarantine mount `<host quarantine dir>:/scan/quarantine`; replace the healthcheck with the watcher liveness check (keep the `autoheal-antivirus` label so a dead watcher self-heals); `mem_limit` stays at 2g (only reached transiently during a scan; idle is ~5 MB).

### Testing (functional, not unit)
- Drop the standard **EICAR** test file into a temp subdir under a `complete/` folder → confirm the watcher scans it, detects `Eicar-Test-Signature`, moves it to quarantine, and logs it.
- Drop a clean file → confirm it is scanned, reported clean, and left in place.
- `docker stats clamav` at idle → confirm ~tens of MB, not ~950 MB.

### Non-goals
- No in-downloader hooks, no docker-socket access, no touching the VPN stacks.
- No auto-delete (quarantine only). No initial bulk scan of the 150 pre-existing `complete/` items on startup (only new arrivals are scanned; a manual full scan remains available on demand).

---

## Part B — Home Assistant → InfluxDB: replace the LAN IP with loopback

### Problem
Task 3 pointed HA at InfluxDB via the Pi LAN IP (`host: 192.168.1.2`) because HA could not resolve the container name `influxdb`. That LAN IP is fragile (DHCP/renumbering) and hair-pins traffic out to the LAN and back.

### Why the original "shared Docker network" idea does NOT apply
Home Assistant runs with **`network_mode: host`** (required so it can discover the myStrom plug on the LAN). A host-networked container cannot join a bridge network and cannot resolve Docker service names, so `host: influxdb` is impossible here.

### Design (better fit for host mode)
Because HA is on the host network and InfluxDB **publishes 8086 on the host** (`ports: "8086:8086"`), HA can reach it on the loopback:
- Change `Home-Assistant/config/packages/influxdb.yaml` `host:` from `192.168.1.2` to **`127.0.0.1`** (port 8086 unchanged).
- This is stable (never changes), stays on loopback (no LAN round-trip), and needs no network/compose changes.
- Restart HA; verify it still writes (query the `homeassistant` bucket) and the Grafana dashboard still populates.

### Non-goals
- No Docker network creation or compose network changes (unnecessary and impossible with host mode).

---

## Success criteria
- clamav idle RAM drops from ~950 MB to tens of MB; a completed download is scanned automatically; EICAR is quarantined + logged; clean files untouched.
- HA writes to InfluxDB via `host: influxdb` over the shared network (LAN-IP workaround removed); Grafana dashboard still populated.
- Configs committed (no secrets); download-folder data never committed.
