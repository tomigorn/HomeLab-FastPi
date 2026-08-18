# clamav On-Demand Scanning + HA Loopback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert clamav from a resident ~950 MB daemon into an event-driven watch-and-scan service (idle ~5 MB, quarantines infected completed downloads before manual library moves), and point Home Assistant at InfluxDB via loopback instead of the fragile LAN IP.

**Architecture:** Repurpose the `clamav` container: `inotifywait` watches the two download `complete/` folders; each finished item triggers a one-shot `clamscan --move` (loads DB, scans, exits → RAM freed). `freshclam --daemon` keeps definitions current. Separately, change HA's InfluxDB `host` to `127.0.0.1` (HA is host-networked; InfluxDB publishes 8086 on the host).

**Tech Stack:** Alpine + `clamav-scanner` (clamscan) + `freshclam` + `inotify-tools`; Docker Compose; Home Assistant `influxdb:` integration.

**Note (infra plan):** Infrastructure, not unit-testable code. Each task = concrete edit → verification command with expected output → commit. Runs on host `fastpi`. Repo root `/home/pi/Projects` (branch `main`). Commit prefix convention `Project: description`. NEVER add an AI co-author trailer. Do NOT push. Stage only listed files; leave unrelated modified files alone.

---

## File map

- `Docker/antivirus/clamav/freshclam.conf` — drop `NotifyClamd` (no clamd anymore)
- `Docker/antivirus/clamav/entrypoint.sh` — replace with watch-and-scan loop
- `Docker/antivirus/clamav/Dockerfile` — packages (`clamav-scanner`, `inotify-tools`), drop clamd bits, new healthcheck, drop `EXPOSE 3310`
- `Docker/antivirus/clamav/clamd.conf` — delete (unused by clamscan)
- `Docker/antivirus/docker-compose.yaml` — clamav service: drop port 3310, download mounts `:ro`→rw, add quarantine mount, new healthcheck
- `Docker/Home-Assistant/config/packages/influxdb.yaml` — `host: 192.168.1.2` → `host: 127.0.0.1`

---

## Task A1: Rewrite clamav container files

**Files:**
- Modify: `Docker/antivirus/clamav/freshclam.conf`
- Modify: `Docker/antivirus/clamav/entrypoint.sh`
- Modify: `Docker/antivirus/clamav/Dockerfile`
- Delete: `Docker/antivirus/clamav/clamd.conf`
- Modify: `Docker/antivirus/docker-compose.yaml`

- [ ] **Step 1: Replace `freshclam.conf`** with (removes the `NotifyClamd` line, since clamd is gone):

```
DatabaseDirectory /var/lib/clamav
LogTime yes
LogVerbose no
Checks 24
DatabaseMirror database.clamav.net
```

- [ ] **Step 2: Replace `entrypoint.sh`** with the watch-and-scan loop:

```sh
#!/bin/sh
set -e

DB_DIR=/var/lib/clamav
QUARANTINE=/scan/quarantine
WATCH_DIRS="/scan/sabnzbd/complete /scan/qbittorrent/complete"

mkdir -p "$QUARANTINE"
for d in $WATCH_DIRS; do mkdir -p "$d"; done

# First-run: fetch definitions if the volume is empty.
if [ ! -f "${DB_DIR}/main.cvd" ] && [ ! -f "${DB_DIR}/main.cld" ]; then
    echo "[entrypoint] No virus definitions found — downloading now (a few minutes)..."
    freshclam --config-file=/etc/clamav/freshclam.conf --no-dns || true
fi

# Keep definitions updated. freshclam is light and does NOT hold the scan DB
# resident in RAM the way clamd did.
freshclam --daemon --config-file=/etc/clamav/freshclam.conf &

echo "[entrypoint] Watching for completed downloads in: $WATCH_DIRS"
echo "[entrypoint] Infected files will be moved to: $QUARANTINE"

# Event-driven: fires when a finished job is written/moved into complete/.
# clamscan loads the DB, scans, and exits — so RAM is used only during a scan.
inotifywait -m -r -e close_write -e moved_to --format '%w%f' $WATCH_DIRS 2>/dev/null | while read TARGET; do
    case "$TARGET" in "$QUARANTINE"/*) continue ;; esac
    sleep 5   # debounce: let a multi-file job settle
    [ -e "$TARGET" ] || continue
    echo "[scan] $(date -Is) scanning: $TARGET"
    if clamscan -r -i --move="$QUARANTINE" "$TARGET"; then
        echo "[scan] CLEAN: $TARGET"
    else
        rc=$?
        if [ "$rc" -eq 1 ]; then
            echo "[scan] !!!! INFECTED — moved to quarantine: $TARGET"
        else
            echo "[scan] scan ERROR (rc=$rc): $TARGET"
        fi
    fi
done
```

- [ ] **Step 3: Replace `Dockerfile`** with (installs `clamav-scanner` for `clamscan` + `inotify-tools`, drops clamd/netcat, creates the clamav user defensively, new healthcheck, no `EXPOSE 3310`):

```dockerfile
FROM alpine:latest

RUN apk add --no-cache clamav-scanner clamav-libs freshclam inotify-tools

RUN (addgroup -S clamav 2>/dev/null || true) && \
    (adduser -S -H -s /sbin/nologin -G clamav clamav 2>/dev/null || true) && \
    mkdir -p /var/lib/clamav /run/clamav && \
    chown -R clamav:clamav /var/lib/clamav /run/clamav

COPY freshclam.conf /etc/clamav/freshclam.conf
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh && \
    chown clamav:clamav /etc/clamav/freshclam.conf

VOLUME /var/lib/clamav

HEALTHCHECK --interval=60s --timeout=10s --retries=3 --start-period=120s \
  CMD pgrep inotifywait >/dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
```

- [ ] **Step 4: Delete the now-unused clamd config:**

Run: `rm -f /home/pi/Projects/Docker/antivirus/clamav/clamd.conf`

- [ ] **Step 5: Edit the `clamav` service in `Docker/antivirus/docker-compose.yaml`** to this exact block (removes `ports: 3310`, makes the two `/scan/*` mounts read-write, adds the quarantine mount, replaces the healthcheck):

```yaml
  clamav:
    build: ./clamav
    image: clamav-local:latest
    container_name: clamav
    mem_limit: 2g
    restart: unless-stopped
    labels:
      - autoheal-antivirus=true
    environment:
      - FRESHCLAM_CHECK_INTERVAL=${FRESHCLAM_CHECK_INTERVAL:-60}
    volumes:
      - clamav-db:/var/lib/clamav
      - /mnt/seagate-red/sabnzbd/config/Downloads:/scan/sabnzbd
      - /mnt/seagate-red/qbittorrent/downloads:/scan/qbittorrent
      - /mnt/seagate-red/antivirus-quarantine:/scan/quarantine
    healthcheck:
      test: ["CMD-SHELL", "pgrep inotifywait >/dev/null || exit 1"]
      interval: 60s
      retries: 3
      start_period: 120s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - antivirus_network
```

(Leave the `autoheal-antivirus` and `virustotal` services, the `networks:` and `volumes:` sections unchanged.)

---

## Task A2: Build, deploy, and functionally verify clamav

**Files:** none (build/test/commit only)

- [ ] **Step 1: Create the quarantine dir on the host** (same disk as downloads → atomic moves):

Run: `mkdir -p /mnt/seagate-red/antivirus-quarantine && echo ok`
Expected: `ok`.

- [ ] **Step 2: Rebuild and recreate clamav:**

Run: `cd /home/pi/Projects/Docker/antivirus && docker compose up -d --build clamav`
Expected: image builds without error; `Container clamav  Started` (recreated).

- [ ] **Step 3: Confirm the watcher is running and clamscan exists:**

Run: `docker exec clamav sh -c 'pgrep -a inotifywait; which clamscan'`
Expected: an `inotifywait ... /scan/...` process line, and `/usr/bin/clamscan`.

- [ ] **Step 4: Confirm idle RAM collapsed (the whole point):**

Run: `docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' clamav`
Expected: tens of MB (e.g. under ~100 MiB), NOT ~950 MiB. (If definitions are still downloading on first boot, wait for that to finish and re-check.)

- [ ] **Step 5: EICAR detection test — create the standard AV test file in a completed-download folder:**

```bash
mkdir -p /mnt/seagate-red/sabnzbd/config/Downloads/complete/_avtest
printf '%s' 'X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*' \
  > /mnt/seagate-red/sabnzbd/config/Downloads/complete/_avtest/eicar.com
sleep 15
```

- [ ] **Step 6: Verify EICAR was detected, quarantined, and logged:**

```bash
docker logs --since 60s clamav 2>&1 | grep -iE 'scanning|INFECTED|CLEAN|quarantine' | tail
echo "--- source should be GONE: ---"; ls /mnt/seagate-red/sabnzbd/config/Downloads/complete/_avtest/
echo "--- quarantine should CONTAIN it: ---"; ls -la /mnt/seagate-red/antivirus-quarantine/
```
Expected: a log line `INFECTED — moved to quarantine` for the eicar path; `eicar.com` no longer in `_avtest/`; `eicar.com` present in the quarantine dir.

- [ ] **Step 7: Clean-file test — a benign file must be scanned and left in place:**

```bash
mkdir -p /mnt/seagate-red/sabnzbd/config/Downloads/complete/_avtest2
echo "totally benign text file" > /mnt/seagate-red/sabnzbd/config/Downloads/complete/_avtest2/clean.txt
sleep 12
docker logs --since 30s clamav 2>&1 | grep -iE 'CLEAN|_avtest2' | tail
ls /mnt/seagate-red/sabnzbd/config/Downloads/complete/_avtest2/
```
Expected: a `CLEAN:` log line for the clean.txt path; `clean.txt` still present in `_avtest2/`.

- [ ] **Step 8: Clean up the test artifacts:**

```bash
rm -rf /mnt/seagate-red/sabnzbd/config/Downloads/complete/_avtest \
       /mnt/seagate-red/sabnzbd/config/Downloads/complete/_avtest2 \
       /mnt/seagate-red/antivirus-quarantine/eicar.com
echo cleaned
```
Expected: `cleaned`.

- [ ] **Step 9: Commit** (stage only the clamav files; the `clamd.conf` deletion is included via `git add -A` on that path):

```bash
cd /home/pi/Projects
git add Docker/antivirus/clamav/Dockerfile Docker/antivirus/clamav/entrypoint.sh \
        Docker/antivirus/clamav/freshclam.conf Docker/antivirus/docker-compose.yaml
git add -A Docker/antivirus/clamav/clamd.conf
git commit -m "Antivirus: clamav on-demand watch-and-scan (quarantine on detection), drop resident clamd"
```

---

## Task B1: Point Home Assistant at InfluxDB via loopback

**Files:**
- Modify: `Docker/Home-Assistant/config/packages/influxdb.yaml`

- [ ] **Step 1: Change the InfluxDB host** in `Docker/Home-Assistant/config/packages/influxdb.yaml` from the LAN IP to loopback. Update the `host:` line and its comment:

```yaml
  # HA runs network_mode: host, and InfluxDB publishes 8086 on the host, so
  # reach it on loopback — stable (no LAN-IP dependency) and stays local.
  host: 127.0.0.1
```
(The file is owned by root:root — edit with sudo if needed. Change only the `host:` value and its comment; leave `port: 8086` and everything else intact.)

- [ ] **Step 2: Restart Home Assistant:**

Run: `docker restart homeassistant`
Then wait ~45 seconds for HA to come up.

- [ ] **Step 3: Verify no InfluxDB connection errors:**

Run: `docker logs --since 90s homeassistant 2>&1 | grep -iE 'influxdb' | head`
Expected: no `connection`/`refused`/`unauthorized`/`resolve` errors (empty output = healthy).

- [ ] **Step 4: Verify HA is still writing to InfluxDB via the new host** (fresh data after the restart):

```bash
cd /home/pi/Projects
TOKEN=$(grep -E '^GRAFANA_INFLUX_TOKEN=' Docker/grafana/.env | cut -d= -f2-)
docker exec influxdb influx query --token "$TOKEN" --org myorg 'from(bucket:"homeassistant")|>range(start:-5m)|>filter(fn:(r)=>r._measurement=="W" and r._field=="value")|>count()|>sum()' 2>&1 | tail -3
```
Expected: a non-zero count (HA wrote power data in the last 5 min through `127.0.0.1`). If zero, wait 2-3 min for HA to flush and retry.

- [ ] **Step 5: Commit:**

```bash
cd /home/pi/Projects
git add Docker/Home-Assistant/config/packages/influxdb.yaml
git commit -m "Home-Assistant: reach InfluxDB via loopback instead of LAN IP"
```

---

## Self-review notes

- **Spec coverage:** Part A daemon→watch-scan (A1) ✓; quarantine+log on detection (A1 entrypoint `--move`, A2 Step 6) ✓; idle RAM drop (A2 Step 4) ✓; EICAR + clean tests (A2 Steps 5-7) ✓; no downloader/VPN/socket changes ✓; Part B loopback replacing LAN IP (B1) ✓; Grafana still populated (implicitly verified by B1 Step 4 querying the same bucket the dashboard reads) ✓.
- **Placeholder scan:** none — all configs, the EICAR string, and commands are literal.
- **Consistency:** quarantine path `/scan/quarantine` (container) = `/mnt/seagate-red/antivirus-quarantine` (host) used identically in entrypoint, compose mount, and tests. Watch dirs match the compose `/scan/sabnzbd` + `/scan/qbittorrent` mounts.
- **Known risks:** (1) alpine package names — verified `clamav-scanner` provides `/usr/bin/clamscan` and `inotify-tools` provides `inotifywait`; if `clamav` user isn't created by the packages, the Dockerfile creates it defensively. (2) `--move` needs write on the download folders — handled by dropping `:ro`. (3) First boot re-downloads definitions into the existing `clamav-db` volume only if empty (it isn't), so no long delay expected on recreate.
