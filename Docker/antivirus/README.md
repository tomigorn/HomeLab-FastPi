# Antivirus

ClamAV scans on fastpi, plus a VirusTotal helper for a second opinion. `clamav/scan.sh` is the one source of truth, copied verbatim to beefy and tower.

## What runs when

| What | When | How |
|---|---|---|
| `freshclam` (signature updates) | always, 24 checks a day | container `clamav` (entrypoint), healthcheck `pgrep freshclam` |
| `scan.sh new` | 05:00 daily, catches up after downtime | `clamav-scan.timer` → `clamav-scan.service` → `docker exec clamav /scan.sh new` |
| `scan.sh all` of the host root | timer 22:30 every night; scans only 22:00-06:00 and all day Sunday, one pass a week, resumes the next night | `clamav-hostscan.timer` → `clamav-hostscan.service` → `docker compose run --rm clamav-hostscan` (container without network) |
| `scan.sh all` of the disks, `scan.sh <path>…` | by hand | see below |

Install / reinstall the units (both timers): `Docker/antivirus/install.sh`.

## Modes

| Command on fastpi | Scans | Infected files |
|---|---|---|
| `docker exec clamav /scan.sh new` | files under `/scan/seagate-red` and `/scan/seagate-black` changed since the last good run | moved to quarantine |
| `docker exec clamav /scan.sh all` | both disks only (`SCAN_HOST=0`; the container has no `/host`) | report only |
| `docker compose run --rm clamav-hostscan` (nightly timer) | the host root, one filesystem, as `/host`, minus the exclude list (below), in resumable chunks | report only |
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
| Not scanned (`SCAN_EXCLUDE_DIRS`) | list and reasons: next section. Container writable layers drop out of the weekly scan (accepted) |
| Back to one thread | `USE_CLAMD=0` (`clamscan -r`), `SCAN_EXCLUDE_DIRS` is honoured there too |
| Settings | `CLAMD_THREADS` (default `nproc`), `CLAMD_WAIT` (seconds to wait for the signature load, 600), `CLAMD_CONF`, `CLAMD_SOCK` |
| Allow list | each entry becomes a clamd `ExcludePath`, like `--exclude` for clamscan |

## Weekly host scan: scope, schedule, resume

Cause of the old 12 h run (2026-10-25/26): the whole root filesystem (1.45 M files, 122 GB incl. unpacked archives) with single-threaded `clamscan`, at default priority, over Docker layers, backups, ISOs and caches.

| Exclude (under `/host`) | Why |
|---|---|
| `/var/lib/docker/{overlay2,containerd,image,buildkit,buildkit.backup,tmp}`, `/var/lib/containerd` | image layers and build stores, rebuilt from images (the bulk: ~1.5 M files) |
| `/var/lib/docker/volumes/monitoring__grafana_{influxdb,prometheus}_data` | time-series databases, 5 GB of numbers |
| `/home/pi/backups` | our own tarballs of configs and databases (13 GB), made on this host |
| `/home/pi/Documents/iso` | installer images (7 GB), checksummed downloads |
| `/home/pi/.cache`, `/home/pi/.npm`, `/var/cache/apt`, `/var/lib/security-scan/trivy-cache` | re-downloadable caches and the public vulnerability DB |

- Media, audiobook and download folders are on `/mnt/seagate-*`: separate filesystems, never part of this scan (one filesystem, `--cross-fs=no`), covered by `scan.sh new`.
- Stays in: `/etc`, `/usr`, `/opt`, `/boot`, `/root`, `/home` (repos, `.vscode-server`, `.config`), `/var/lib/docker/volumes` (rest), `/var/log`, `/config`.
- Scope now: about 289 000 files, 21 GB (was 1.8 M files, 100 GB with layers). Estimate: roughly 1 to 2.5 h with 4-thread clamd multiscan, so normally one night.
- Priority: `nice -n 19` + `ionice -c 3` inside the container, `cpu_shares: 2`, and `Nice=19` / `CPUSchedulingPolicy=idle` / `IOSchedulingClass=idle` on the unit (only the `docker` client, the container's own settings do the work).
- Window (`Europe/Zurich`, the host's `/etc/localtime` is mounted): scanning only 22:00-06:00 every day and all day Sunday (low tariff). Nothing Mon-Sat 06:00-22:00. The timer fires 22:30 nightly; outside the window the script exits at once.
- Pass and resume: the file list is built once (sorted, `all.list`), scanned in chunks of `CHUNK_FILES` (20 000); `all.done` = files finished. Before every chunk the remaining window is read; a chunk still running at 06:00 is killed and repeated. Next night it continues at `all.done`.
- Weekly cadence: a finished pass (`all.finished`) blocks a new one for 6 days; the next pass starts at the following 22:30 and builds a fresh list.
- Alerts: `clamav.prom` `mode="all"` is rewritten after every session: `clamav_files_listed` = pass size, `clamav_files_scanned` = done so far, `clamav_infected_last_run` = hits of the whole pass (`all.pass-hits`, reset when a new pass starts), so `MalwareFound` stays up across nights. Exit 1 only for hits found in that session.
- Pass in progress: `cat /var/lib/clamav-scan/all.done` of `wc -l < /var/lib/clamav-scan/all.list`. Restart a pass early: `rm /var/lib/clamav-scan/all.finished`; throw away progress: `rm /var/lib/clamav-scan/all.list`.
- Settings: `SCAN_RESUME`, `CHUNK_FILES`, `PASS_DAYS` (6); test hook `SCAN_NOW_FILE`.

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

`SCAN_ROOTS`, `QUARANTINE`, `STATE`, `TEXTFILE`, `HOST`; optional `SCAN_RESUME`, `CHUNK_FILES`, `PASS_DAYS` (Weekly host scan: scope), `SCAN_HOST=0` (`all` without `/host`; set in `clamav`, in `clamav-hostscan` `SCAN_ROOTS=/host`), `USE_CLAMD`, `SCAN_EXCLUDE_DIRS` (see Weekly host scan), `SCAN_BTRFS=1` (tower: `btrfs subvolume find-new` instead of `find`), `DB_DIR`.

## Tests

```sh
Docker/antivirus/tests/test_scan.sh
docker run --rm --entrypoint sh -v "$PWD/Docker/antivirus:/src:ro" clamav-local:latest /src/tests/test_scan.sh   # busybox
```

Changing `scan.sh` or `hostscan.sh` needs a rebuild: `docker compose up -d --build clamav` (the hostscan uses the same image).

**Rebuild** (`clamav-local` FROM `alpine:latest`, `virustotal-local` FROM `python:3.12-alpine`): `docker compose up -d --build --pull clamav virustotal` when Cup shows an update for the base or the security scan lists a fixable base CVE, otherwise monthly.

## Retired: download watcher

Until 2026-10-19 the container ran an inotify watcher on `sabnzbd/.../complete` and `qbittorrent/complete`. Replaced by the nightly `new` scan, which also covers both disks; `inotify-tools` is gone from the image.
