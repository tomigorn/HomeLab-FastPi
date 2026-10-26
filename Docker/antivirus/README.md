# Antivirus

ClamAV scans on fastpi, plus a VirusTotal helper for a second opinion. `clamav/scan.sh` is the one source of truth, copied verbatim to beefy and tower.

## What runs when

| What | When | How |
|---|---|---|
| `freshclam` (signature updates) | always, 24 checks a day | container `clamav` (entrypoint), healthcheck `pgrep freshclam` |
| `scan.sh new` | 05:00 daily, catches up after downtime | `clamav-scan.timer` → `clamav-scan.service` → `docker exec clamav /scan.sh new` |
| `scan.sh all` of the host root | Sunday 01:30, catches up after downtime | `clamav-hostscan.timer` → `clamav-hostscan.service` → `docker compose run --rm clamav-hostscan` (container without network) |
| `scan.sh all` of the disks, `scan.sh <path>…` | by hand | see below |

Install / reinstall the units (both timers): `Docker/antivirus/install.sh`.

## Modes

| Command on fastpi | Scans | Infected files |
|---|---|---|
| `docker exec clamav /scan.sh new` | files under `/scan/seagate-red` and `/scan/seagate-black` changed since the last good run | moved to quarantine |
| `docker exec clamav /scan.sh all` | both disks only (`SCAN_HOST=0`; the container has no `/host`) | report only |
| `docker compose run --rm clamav-hostscan` (weekly timer) | the host root, one filesystem, as `/host`, without Docker image layers (below) | report only |
| `docker exec clamav /scan.sh /scan/seagate-red/qbittorrent/downloads/<folder>` | the given files/folders | moved when under `/scan/...`, report only otherwise |

- Paths are as seen in the container: `/mnt/seagate-red/x` = `/scan/seagate-red/x`; in `clamav-hostscan` `/etc/x` = `/host/etc/x`.
- "Changed" = ctime or mtime newer than the marker, so unpacked archives with old mtimes count. First run (no marker): the last 24 h.
- Skipped by `new`: the quarantine, `*/quarantine/*`, `*/.snapshots/*`, `*/incomplete/*`, qBittorrent's own `*/qBittorrent/logs/*` (written 0600, unreadable to the scanner), `*.part`, `*.!qB`, SQLite `*-wal`, `*-shm`, `*-journal`.
- A file deleted between listing and scanning (clamscan `No such file or directory` + `Can't access file`) is not an error: counted in `clamav_files_vanished`. Unreadable files and other failures stay errors.
- Exit codes: `0` clean, `1` infected, `2` errors. On errors `new` keeps its marker, so the next run retries the same files.
- The quarantine folder must exist: when seagate-red is not mounted every run fails with exit 2 instead of scanning an empty mountpoint.
- Files over 2 GiB (most films) are size-skipped by ClamAV itself (`--max-filesize=2047M`, its real limit); counted in `clamav_files_skipped_large`.
- Logs: `journalctl -u clamav-scan`, last output per mode in `/var/lib/clamav-scan/last-<mode>.log`.

## Two containers, why

| | `clamav` (always on) | `clamav-hostscan` (weekly, exits) |
|---|---|---|
| Network | yes (freshclam) | `none` (only `lo`) |
| Host root | not mounted | `/:/host:ro` |
| Virus DB | `clamav-db` rw (freshclam) | same volume, read-only |
| User / caps | 65039, no caps | root, `DAC_READ_SEARCH` (read all) + `DAC_OVERRIDE` + `CHOWN` (state hand-back), read-only root fs, tmpfs `/tmp` |
| Writes | quarantine, state, textfile | state, textfile only |

- A container with internet egress must not see the whole host (a malicious file or scanner bug could exfiltrate it): the part that reads everything has no network.
- Root is needed because a non-root uid gets no effective capabilities in Docker (`CapEff` 0), so `DAC_READ_SEARCH` does nothing for 65039. `hostscan.sh` chowns state and `clamav.prom` back to 65039 / `65039:65046`.
- Same state dir, so one `clamav.prom` with `mode="all"` next to `new` and `path`.
- Smaller run, e.g. `docker compose run --rm -e SCAN_ROOTS=/host/etc clamav-hostscan` (the compose profile `hostscan` keeps it out of `up`).

## Weekly host scan: speed

| | |
|---|---|
| Engine | `USE_CLAMD=1`: `scan.sh all` starts a private `clamd` in the container (socket and config in `/tmp`, no network, signatures from the read-only `clamav-db` volume) and runs `clamdscan --multiscan`: all cores, one signature load (~1 GB RAM, hence `mem_limit: 3g`) |
| Same output | clamdscan prints the same `path: Sig FOUND` lines, so `hits.tsv`, `last-infected.txt`, the metrics and the alerts are unchanged. `Scanned files` (not printed by clamdscan) is counted with `find` using the same excludes and size limit |
| Not scanned (`SCAN_EXCLUDE_DIRS`) | `/var/lib/docker/{overlay2,containerd,image,buildkit}`, `/var/lib/containerd`. Container writable layers drop out of the weekly scan (accepted). `/var/lib/docker/volumes` (user data) stays in |
| Back to one thread | `USE_CLAMD=0` (`clamscan -r`), `SCAN_EXCLUDE_DIRS` is honoured there too |
| Settings | `CLAMD_THREADS` (default `nproc`), `CLAMD_WAIT` (seconds to wait for the signature load, 600), `CLAMD_CONF`, `CLAMD_SOCK` |
| Allow list | each entry becomes a clamd `ExcludePath`, like `--exclude` for clamscan |

## Results

| Where (host) | What |
|---|---|
| `/mnt/seagate-red/antivirus-quarantine/` | quarantined files |
| `/mnt/seagate-red/antivirus-quarantine/index.txt` | one line per quarantined file: date (UTC) TAB original path TAB signature; read every 15 min for the `MalwareQuarantined` alert (`Server/4-Security-Monitoring/README.md`, Quarantined hits) |
| `/var/lib/clamav-scan/last-infected.txt` | hits of the last run that found something: path TAB signature |
| `/var/lib/clamav-scan/` | state (shared by both containers): `last-run` marker, `infected-total`, `new.list`, `allow.txt` (restored false positives) |
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

API key: file `secrets/vt_api_key` (owner `65014`, mode `0400`, read via `VT_API_KEY_FILE`), not an env variable.

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

`SCAN_ROOTS`, `QUARANTINE`, `STATE`, `TEXTFILE`, `HOST`; optional `SCAN_HOST=0` (`all` without `/host`; set in `clamav`, in `clamav-hostscan` `SCAN_ROOTS=/host`), `USE_CLAMD`, `SCAN_EXCLUDE_DIRS` (see Weekly host scan), `SCAN_BTRFS=1` (tower: `btrfs subvolume find-new` instead of `find`), `DB_DIR`.

## Tests

```sh
Docker/antivirus/tests/test_scan.sh
docker run --rm --entrypoint sh -v "$PWD/Docker/antivirus:/src:ro" clamav-local:latest /src/tests/test_scan.sh   # busybox
```

Changing `scan.sh` or `hostscan.sh` needs a rebuild: `docker compose up -d --build clamav` (the hostscan uses the same image).

**Rebuild** (`clamav-local` FROM `alpine:latest`, `virustotal-local` FROM `python:3.12-alpine`): `docker compose up -d --build --pull clamav virustotal` when Cup shows an update for the base or the security scan lists a fixable base CVE, otherwise monthly.

## Retired: download watcher

Until 2026-10-19 the container ran an inotify watcher on `sabnzbd/.../complete` and `qbittorrent/complete`. Replaced by the nightly `new` scan, which also covers both disks; `inotify-tools` is gone from the image.
