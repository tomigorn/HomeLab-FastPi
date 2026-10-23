# Antivirus

ClamAV scans on fastpi, plus a VirusTotal helper for a second opinion. `clamav/scan.sh` is the one source of truth, copied verbatim to beefy and tower.

## What runs when

| What | When | How |
|---|---|---|
| `freshclam` (signature updates) | always, 24 checks a day | container `clamav` (entrypoint), healthcheck `pgrep freshclam` |
| `scan.sh new` | 05:00 daily, catches up after downtime | `clamav-scan.timer` → `clamav-scan.service` → `docker exec clamav /scan.sh new` |
| `scan.sh all`, `scan.sh <path>…` | by hand | see below |

Install / reinstall the units: `Docker/antivirus/install.sh`.

## Modes

| Command on fastpi | Scans | Infected files |
|---|---|---|
| `docker exec clamav /scan.sh new` | files under `/scan/seagate-red` and `/scan/seagate-black` changed since the last good run | moved to quarantine |
| `docker exec clamav /scan.sh all` | both disks and the host root (`/host`, read-only, one filesystem); takes hours | report only |
| `docker exec clamav /scan.sh /scan/seagate-red/qbittorrent/downloads/<folder>` | the given files/folders | moved when under `/scan/...`, report only for `/host/...` |

- Paths are as seen in the container: `/mnt/seagate-red/x` = `/scan/seagate-red/x`, `/etc/x` = `/host/etc/x`.
- "Changed" = ctime or mtime newer than the marker, so unpacked archives with old mtimes count. First run (no marker): the last 24 h.
- Skipped by `new`: the quarantine, `*/quarantine/*`, `*/.snapshots/*`, `*/incomplete/*`, `*.part`, `*.!qB`, SQLite `*-wal`, `*-shm`, `*-journal`.
- A file deleted between listing and scanning (clamscan `No such file or directory` + `Can't access file`) is not an error: counted in `clamav_files_vanished`. Unreadable files and other failures stay errors.
- Exit codes: `0` clean, `1` infected, `2` errors. On errors `new` keeps its marker, so the next run retries the same files.
- The quarantine folder must exist: when seagate-red is not mounted every run fails with exit 2 instead of scanning an empty mountpoint.
- Files over 2 GiB (most films) are size-skipped by ClamAV itself (`--max-filesize=2047M`, its real limit); counted in `clamav_files_skipped_large`.
- Logs: `journalctl -u clamav-scan`, last output per mode in `/var/lib/clamav-scan/last-<mode>.log`.

## Results

| Where (host) | What |
|---|---|
| `/mnt/seagate-red/antivirus-quarantine/` | quarantined files |
| `/mnt/seagate-red/antivirus-quarantine/index.txt` | one line per quarantined file: date (UTC) TAB original path TAB signature |
| `/var/lib/clamav-scan/last-infected.txt` | hits of the last run that found something: path TAB signature |
| `/var/lib/clamav-scan/` | state: `last-run` marker, `infected-total`, `new.list`, `allow.txt` (restored false positives) |
| `/var/lib/node-exporter/textfile/clamav.prom` | metrics for Prometheus |

## False positive

`docker exec clamav /scan.sh restore '<file name in antivirus-quarantine>'`: moves it back to its original path from `index.txt`, marks that line `restored <date>` and adds the path to `/var/lib/clamav-scan/allow.txt`, which every mode skips (exact path). Refuses when the original path exists again.

## Second opinion: VirusTotal

The `virustotal` container sees the download folders (`/scan/sabnzbd`, `/scan/qbittorrent`), not the quarantine.

```sh
docker exec virustotal python /scan.py /scan/qbittorrent/<file>
docker cp /mnt/seagate-red/antivirus-quarantine/<file> virustotal:/tmp/ && docker exec virustotal python /scan.py /tmp/<file>
```

Unknown files are uploaded to VirusTotal: not for private files.

## Metrics (`clamav.prom`)

| Metric | Labels |
|---|---|
| `clamav_last_run_timestamp_seconds` | host, mode |
| `clamav_run_duration_seconds` | host, mode |
| `clamav_files_listed` | host, mode |
| `clamav_files_scanned` | host, mode |
| `clamav_scan_errors` | host, mode |
| `clamav_files_vanished` (deleted before the scan reached them) | host, mode |
| `clamav_infected_last_run` | host, mode |
| `clamav_files_skipped_large` (over 2047M, not scanned) | host, mode |
| `clamav_infected_total` (counter, persisted) | host |
| `clamav_signature_age_seconds` (from the daily DB build time) | host |
| `clamav_db_version` | host |

`mode` is `new`, `all` or `path`; each mode keeps its last values.

## Settings (env in `docker-compose.yaml`)

`SCAN_ROOTS`, `QUARANTINE`, `STATE`, `TEXTFILE`, `HOST`; optional `SCAN_HOST=0` (`all` without `/host`), `SCAN_BTRFS=1` (tower: `btrfs subvolume find-new` instead of `find`), `DB_DIR`.

## Tests

```sh
Docker/antivirus/tests/test_scan.sh
docker run --rm --entrypoint sh -v "$PWD/Docker/antivirus:/src:ro" clamav-local:latest /src/tests/test_scan.sh   # busybox
```

Changing `scan.sh` needs a rebuild: `docker compose up -d --build clamav`.

**Rebuild** (`clamav-local` FROM `alpine:latest`, `virustotal-local` FROM `python:3.12-alpine`): `docker compose up -d --build --pull clamav virustotal` when Cup shows an update for the base or the security scan lists a fixable base CVE, otherwise monthly.

## Retired: download watcher

Until 2026-10-19 the container ran an inotify watcher on `sabnzbd/.../complete` and `qbittorrent/complete`. Replaced by the nightly `new` scan, which also covers both disks; `inotify-tools` is gone from the image.
