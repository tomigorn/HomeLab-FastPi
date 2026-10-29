# Security monitoring

Security questions, answered on a schedule and routed into the alerting
pipeline that already exists (`security_scan.py <group>`):

| Concern | Group | What answers it | Hosts | Cadence |
|---|---|---|---|---|
| Are any secrets public? | `secrets` | gitleaks over the published GitHub history of both repos | repos | daily 04:05 |
| Could a secret become public? | `secrets` | filename hygiene check + a pre-commit hook | fastpi | daily / every commit |
| Is the OS patched? | `patches` | `apt list --upgradable`, security updates counted separately | fastpi, beefy | daily 04:05 |
| Is Unraid patched? | `patches` | `plugin checkall` + `unraidcheck` (json, no Unraid notification) | tower | daily 04:05 |
| Brute force on SSH? | `logins` | failed-login lines in the last 24 h | all three | daily 04:05 |
| Who logged in over SSH (sshd is key-only, so no failures)? | `access` | accepted logins in the last 24 h by user and source class (lan 192.168.1.0/24, vpn 10.24.5.5 + 10.8.0.0/24, tunnel 172.20.0.0/16 = cloudflared, other); alerts on non-lan or a user other than `pi` | fastpi | every 5 min (`security-access.timer`, root, runs the root-owned copy `/usr/local/libexec/fastpi/security_scan.py`: after editing `security_scan.py` run `Docker/_global/install-root-scripts.sh`) |
| Did authorized_keys, sudoers or sshd_config change? | `access` | SHA-256 of `/home/*/.ssh/authorized_keys`, `/root/.ssh/authorized_keys`, `/etc/sudoers`, `/etc/sudoers.d/*`, `/etc/ssh/sshd_config(.d/*)` against a baseline | fastpi | every 5 min |
| Image updates per host? | `cup` | Cup's JSON per `server`; refreshes Cup first when beefy or tower is awake (once per run; a host that is off is reported as skipped, not as an error; its last figures and snapshot time stay, see "Cup snapshot of a sleeping host") | all three | daily 04:05 |
| Malware? | `av` | pulls the ClamAV results of the nightly scans (`Docker/antivirus`; beefy 04:05, fastpi and tower 05:00) | all three | daily 04:20 (beefy), 05:40, 05:50 (fastpi, tower); never wakes beefy or tower, a sleeping host is skipped |
| Was anything quarantined (nightly, beefy's download hook and queue)? | `avhits` (also inside `av`) | each host's quarantine `index.txt`, see "Quarantined hits" | all three | every 15 min (`security-av-hits.timer`); beefy/tower only while the Waker sees them up, always via `-direct` (never wakes) |
| Are container images vulnerable? | `images` | Trivy across the images actually running; new fixable CRITICAL/HIGH findings diffed against `vulns-seen-<host>.json` | all three | daily 04:10 |
| Do the images in the code have a NEW CVE? | `code` | every image the two repos refer to (compose `image:`, Dockerfile `FROM`), cached SBOMs matched against the current Trivy DB; alert per new finding | repos | daily 03:40 (`security-code-scan.timer`) |
| One CVE dashboard over everything that runs? | `dt` | CycloneDX SBOM per running image (fastpi: local Docker; beefy: registry copy of the running digest, built on fastpi; local beefy builds via their Dockerfile base) + one OS SBOM per host (Trivy `rootfs` over os-release, lsb-release (Ubuntu), debian_version, dpkg status) uploaded to Dependency-Track on beefy, see "Dependency-Track" | fastpi, beefy (tower: Unraid/Slackware, no Trivy OS support) | daily 04:02 (`security-dt.timer`), only if DT answers |
| Are images updated? | `updates` (beefy's result) | tiered auto-update with rollback, see [auto-updates.md](auto-updates.md); beefy's `auto_update.prom` republished as `auto_update_beefy.prom` | fastpi, beefy | daily 03:10 fastpi, 04:12 beefy (`auto-update.timer`); pull 04:20 (with `av`) |
| Rootkit / hardening? | `audit` | rkhunter, chkrootkit, Lynis | fastpi, beefy | weekly Sun 04:05 |
| Tagged titles still without their audio language (not security, same pull) | `media` | beefy's `media-language.prom` (Movie-Downloads `language-missing.py`), republished as `media_language_beefy.prom`; alert `AudioLanguageNotFound` (`grafana/prometheus/rules/media-language.yml`) | beefy | daily 04:20 (with `av`) |
| Everything in one message | - | `WeeklyUpdateDigest` alert (`grafana/prometheus/rules/weekly-digest.yml`) | - | Mon 05:00 local |

Metrics:

| Metric | Labels |
|---|---|
| `security_failed_logins_total` | host |
| `security_ssh_logins`, `security_ssh_last_login_timestamp_seconds` | host, user, source_class |
| `security_integrity_changed` (1 = changed, new or missing), `security_integrity_file_info` (12-hex hash prefix), `security_integrity_files` | host, path / + sha256_prefix / host |
| `security_unraid_os_update`, `security_unraid_plugin_update` | installed, available / plugin |
| `security_image_updates`, `security_image_update_info` | host, type / host, reference, type |
| `security_cup_snapshot_timestamp_seconds` | host |
| `clamav_*` (republished as `clamav_<host>.prom`, beefy's hook as `clamav_hook_beefy.prom`), `security_av_infected_info` | host, mode / host, path, signature |
| `clamav_quarantine_hit_first_seen_timestamp_seconds` (one per hit, 24 h, newest 20), `clamav_quarantine_hits_24h` | host, mode, title, file, path, signature, time / host, mode |
| `security_rootkit_warnings` (new), `security_rootkit_findings` (all), `security_rootkit_new_fingerprint` (hash of the new set, 0 = none) | host, tool |
| `security_lynis_hardening_index`, `security_lynis_warnings` | host |
| `security_code_images`, `…_scanned`, `…_unresolved`, `security_code_vulnerabilities_fixable` | scope (`code-fastpi`, `code-beefy`) / + severity |
| `security_new_vulns`, `security_new_vuln_info` (first seen < 24 h, newest 20) | scope (host or `code-<repo>`) / + image, id, pkg, severity |
| `auto_update_result`, `auto_update_omitted`, `auto_update_last_run_timestamp_seconds` (no HELP lines: two hosts' files share the families) | host, project, tier, ref, result, from, to, command / host |
| `security_dt_projects`, `security_dt_uploads`, `security_dt_sbom_failed`, `security_dt_stale_deleted` | host |
| `media_language_missing_since_timestamp_seconds`, `…_notify_timestamp_seconds` (republished from beefy) | app, title, language, failed |

Everything lands as Prometheus metrics via node-exporter's textfile collector
and alerts through `grafana/prometheus/rules/security-posture.yml`, `auto-updates.yml`, `antivirus.yml`
and `weekly-digest.yml` → Alertmanager → email + Telegram (severity info = Telegram
only). Dashboard: **Grafana > fastpi > Updates & security**,
https://grafana.holy-grail.ch/d/updates-security. There is no second notifier and no
second place the Telegram token lives.

## Dependency-Track

DT itself: `HomeLab-BeefyServer` `Docker/Dependency-Track/README.md` (beefy `192.168.1.102:8090`, UI + `/api`).

| | |
|---|---|
| Project | `<host>/<repository without registry>`, version = tag (digest-only refs: `sha256:<12 hex>`, local beefy builds: `<tag> (base <image>)`), child of the parent project `<host>` (aggregates its children); OS: `<host>/os`, version `<id> <version_id>` |
| Upload | `PUT /api/v1/bom` (autoCreate, isLatest), only when the image id/digest (OS: dpkg status hash) changed or the project is missing in DT; `dt-index.json` |
| Image list | each container's `Config.Image` (`docker ps` drops the digest of a pinned `tag@sha256`, and an image pulled by digest has no local tag); fastpi scans `repo@sha256` refs by digest. A beefy digest the registry refuses (fresh local build, kept in `dt-local.json`) is uploaded via its base image in the same run |
| SBOM cache | `/var/lib/security-scan/sbom-dt/` by image id/digest (same key = same content); own Trivy cache `trivy-cache-dt` (no vuln DB needed; Java DB = the image scan's copy, mounted read-only) |
| Stale | projects under `<host>/` that the host no longer runs are **deleted** (not deactivated: DT data is derived, the next upload recreates it; inactive projects would pile up one per old tag). Only for a host whose image list was read this run |
| Asleep | TCP probe of DT first; closed = NoData, beefy is never woken (`DT_URL`, env `SECSCAN_DT_URL`) |
| Key | `/var/lib/security-scan/secrets/dt-api-key` (pi 0600), team `fastpi-scanner` |
| Firewall | HOST-OUT-GUARD must let uid `pi` reach `192.168.1.102:8090` (`Docker/_global/scripts/host-output-guard.sh`) |

## Triage in Dependency-Track

DT is the one place to triage, Trivy stays the scanner and the alert source. A decision made in DT silences the same CVE in Trivy.

| | |
|---|---|
| Mark a CVE | DT UI (beefy `:8090`) > project `<host>/<image>` > Audit Vulnerabilities > component/CVE > Analysis `Not Affected`, `False Positive` or `Resolved` (+ a comment, it is kept in the VEX file) |
| Not a decision | `In Triage`, `Exploitable`: still counted and alerted |
| Export | `security_scan.py dt` (daily 04:02) writes one OpenVEX file per project with decisions to `/var/lib/security-scan/vex/` (`GET /api/v1/finding/project/<uuid>?suppressed=true`, paged 100 per request for DT 4 and 5; one statement per CVE/GHSA id and alias, product = component purl) |
| Use | image scan (daily 04:10) and code scan (daily 03:40) pass `--vex /vex/<file>` for the image's DT project (name + tag, or digest via `dt-index.json`); nothing is passed for an image without decisions |
| Takes effect | the next run after the 04:02 export; counts, `security_new_vulns` and `NewFixableImageVulnerability` drop it |
| Revoke | set it back to `In Triage`: the file is removed at the next export, the CVE counts again and is alerted as new |
| DT asleep | beefy is never woken; the last exported files stay in use. A project whose export fails keeps its file (`security_dt_vex_export_failed`) |
| Scope | per image: a decision on `fastpi/grafana/grafana` does not touch another image with the same package |
| Metrics | `security_dt_vex_projects`, `security_dt_vex_statements`, `security_dt_vex_export_failed` |

DT-only ids (e.g. OSV `GO-…`) that Trivy does not report change nothing in Trivy.

## Cup snapshot of a sleeping host

Cup's result drops beefy and tower while they sleep. Their figures are not dropped here: the `cup-<host>` data file is left untouched (see "Staleness, not absence"), and every run publishes the time of the cached snapshot (`cup-snapshot-<host>.json`, written whenever the host is in Cup's result) on its own.

| Where | What it shows |
|---|---|
| Metric `security_cup_snapshot_timestamp_seconds{host}` | snapshot time, own file `security_cup_asof_<host>.prom` (separate so the data file's success time stays the real one) |
| Dashboard **Updates & security** > "Cup snapshot as of" | per host: as-of time and age (orange > 36 h, red > 8 days) next to the update counts |
| `WeeklyUpdateDigest` (Images) | `beefy: 22 (snapshot as of <time>)` when the snapshot is older than 36 h; nothing when fresh |

Why here: the digest and the dashboard are the only places that show Cup figures from our own metrics (cup.holy-grail.ch is Cup's own UI, untouched), and the cached figures were already there, only without a date. No new alert: `SecurityScanStale` already covers a snapshot that stays old (14 d for Cup). A host Cup has never returned (tower so far) has no snapshot and no row.

## Install

```bash
./install.sh          # on fastpi; idempotent
```

`install.sh` also runs `install-audit-tools.sh` (rkhunter, chkrootkit, Lynis). beefy:

```bash
ssh beefy 'bash -s' < install-audit-tools.sh
```

| Piece | Value |
|---|---|
| Lynis apt source | `deb [signed-by=/etc/apt/keyrings/cisofy-software-public.gpg] https://packages.cisofy.com/community/lynis/deb/ stable main` in `/etc/apt/sources.list.d/cisofy-lynis.list` |
| Lynis key | `https://packages.cisofy.com/keys/cisofy-software-public.key`, dearmored to `/etc/apt/keyrings/cisofy-software-public.gpg` |
| rkhunter baseline | `sudo rkhunter --propupd` (done by the installer); `APT_AUTOGEN="true"` in `/etc/default/rkhunter` refreshes it after every apt run |
| packaged `chkrootkit.timer` | disabled; `security-audit.timer` runs it weekly |

Done 2026-10-19 on fastpi and beefy.

On beefy only the pre-commit hook is needed (`.gitleaks.toml` +
`.githooks/pre-commit` + `git config core.hooksPath .githooks`); everything else
is driven from fastpi over SSH.

## Why it is shaped this way

**The scan reads GitHub, not the local clone.** The question worth answering is
"is this secret visible to the world", and only the remote can answer it. A
local-only scan misses anything pushed from the Mac or the Bazzite box, and it
cannot see beefy's repo at all on the nights beefy is powered off.

**Both repositories are PUBLIC.** A push is not reversible: rewriting history
does not recall what GitHub has already served, cached or indexed. Once a secret
is pushed, rotation is the only real remedy — which is why the pre-commit hook
matters more than the nightly scan, and why `SecretLeakedInPublicRepo` is the
one alert with `for: 0m`.

**Staleness, not absence.** beefy powers itself off when idle, so its figures are
routinely unobtainable. A collector that fails leaves its previous `.prom` file
untouched rather than writing zero — zero would read as "beefy has no pending
security updates". The `SecurityScanStale` alert watches the timestamps instead.

**Rootkit checkers report against a baseline.** Both tools flag known false positives on a stock system (on beefy, Ubuntu 26.04's uutils coreutils reads as INFECTED to chkrootkit). The first run accepts what it finds, like `rkhunter --propupd`; `security_rootkit_warnings` counts only findings not in `/var/lib/security-scan/audit-accepted-<host>-<tool>.txt`. `RootkitWarning` fires for 25 h when that set changes (`security_rootkit_new_fingerprint`), not while a known finding stays; the Monday digest shows the standing count. chkrootkit findings are its WARNING headers and INFECTED lines, not the paths listed under a header (those change every run: `/proc/<pid>`, scripts in `/tmp`). Report: `audit-<host>.txt`, NEW marks unaccepted findings. Accept again:

```bash
rm /var/lib/security-scan/audit-accepted-<host>-<tool>.txt && sudo systemctl start security-audit.service
```

**Accept a changed authorized_keys / sudoers / sshd_config.** `SecurityFileChanged` clears only when the baseline (`/var/lib/security-scan/integrity-baseline-fastpi.json`, written by the first run) is re-accepted after you checked the change:

```bash
sudo rm /var/lib/security-scan/integrity-baseline-fastpi.json && sudo systemctl start security-access.service
```

Login alerts (`SshLoginOutsideLan`, `SshLoginUnexpectedUser`) stay up for an hour after the login. `SshLoginOutsideLan` via vpn or tunnel (the owner's own logins) is digest-only (`notify: digest`); from any other source it pages. The `access` group runs as root in its own 5-minute unit because sudoers and other users' keys are root-only; it is read-only apart from the two state/metric directories. The leftover `deploy` user's key is in the baseline, so a login by it alerts.

**The audit unit is not sandboxed.** It runs the tools via sudo and they must see the real system (PrivateTmp/ProtectHome would hide what chkrootkit looks at).

**Quarantined hits.** Every moved file is a line in its host's `index.txt`; `MalwareQuarantined` alerts per line, not on `clamav_infected_last_run`, which the next clean run of that mode resets (beefy's hook runs many times a day, and was only pulled at 04:20).

| | |
|---|---|
| Source | fastpi `/mnt/seagate-red/antivirus-quarantine/index.txt`, beefy `/srv/.disks/ssd-hot/quarantine/index.txt` (SSD branch, never spins the HDD), tower `/mnt/data/appdata/clamav/quarantine/index.txt` |
| Sticky | 24 h from when fastpi first saw the line (`av-hits-seen-<host>.json`), so a hit read late (host asleep) still alerts; a `restored` line ends it |
| Baseline | first run: lines before 2026-10-26 21:00 (the EICAR tests) are seen, never alert |
| Mode, title | beefy: from `/var/lib/clamav-scan/textfile/clamav-hits.tsv` (clamav-hook.py: time, `hook`/`queue`, job title, path, signature; matched on time + path + signature). Otherwise inferred: |
| Mode (inferred) | `scan` = path in `last-infected.txt` (scan.sh), beefy otherwise `queue` for media names (clamav-hook.py `MEDIA_EXT`) else `hook` |
| Title (inferred) | folder below `complete/` or `downloads/`, else the parent folder |
| Telegram | route `MalwareQuarantined` → receiver `malware` (email + `tg.malware`, no resolved), one message per host batch |

**Corrupt downloads.** beefy's `download-integrity.py` (SABnzbd/qBittorrent completion, Movie-Downloads README "Download integrity") writes `download-integrity.prom` and `download-integrity-hits.tsv` (time, client, title, path, reason) next to the ClamAV files. `security_scan.py` pulls both like the hit list (`AV_PATHS["beefy"]` `dlprom`/`dlhits`, 04:20 and every 15 min while beefy is up, never wakes it): counters as `download_integrity_beefy.prom`, the last 24 h of corrupt files as `download_integrity_hit_info` (max 20). A missing file is "no data", old figures stay. Subject `dlint-beefy`.

| Alert | Fires on | Route |
|---|---|---|
| `DownloadCorrupt` | `increase(download_integrity_corrupt_total[1d]) > 0` (title, file, reason in the text) | warning: Telegram, muted 22:00-07:00 |
| `DownloadIntegrityErrors` | `increase(download_integrity_errors_total[1d]) > 0` | info: Telegram |
| `DownloadIntegrityMetricsMissing` | no `download_integrity_checked_total` for 3 days while beefy was up, held 2 days (quiet until the first download is checked) | info: Telegram |

The Monday digest lists "corrupt downloads caught this week".

**MalwareFound is "last report-only run had hits"**, `max by (host, mode) (clamav_infected_last_run{mode!~"new|hook|queue"}) > 0` (modes `all`, `path`), not `increase()` of the counter: a counter reset (the EICAR test) read as a hit. Quarantining modes are left to `MalwareQuarantined` (one alert per hit). It clears with the next clean run of that mode. `for: 45m`, so the 04:20 (beefy) or 05:40 pull has put the hit list (`security_av_infected_info`, max 20) into the description first. A missing remote `clamav.prom` is "no data": old file kept, no error. Gap: a `new` hit whose move failed is in neither (scan errors then alert, `ClamavScanErrors`).

**The digest fires on Monday 05:00 local all year.** Prometheus knows only UTC; `homelab:local_utc_offset_hours` (2 from the last Sunday in March to the last Sunday in October, else 1) shifts the clock. Its own Alertmanager route `telegram-digest` sends no resolved message.

**beefy and tower are scanned from fastpi.** Their running image digests are read over ssh first (seconds), then Trivy on fastpi scans the registry copy (`--image-src remote --platform linux/amd64`), so the scan finishes even after beefy powered off. A locally built image (`clamav-local`; no repo digest, or the registry refuses it) is not scanned itself: the registry copies of its Dockerfile `FROM` images are (read over ssh with the digest list: the compose project dir of each running container, `Dockerfile` there and one level down), listed as `(base of a local image)` in `image-cves-<host>.txt`. Only one with no known base is counted in `security_images_local_only{host}`, not as unscannable, so `ImagesUnscannable` stays quiet. fastpi's own local builds are still scanned through its socket proxy.

**On fastpi Trivy reads images through the read-only socket proxy** (`POST=0`), which
the host already runs for Cup and telegraf. Trivy is not made a new Docker socket
consumer: the socket-hardening work cut that list down to Portainer deliberately,
and a `:ro` socket mount protects the socket *file*, not the root-equivalent API
behind it.

## Things that will bite

- **Both socket-proxy networks are `internal: true`**, so a container attached to
  one cannot reach the internet. Trivy's vulnerability DB and its *separate*
  Java index DB are therefore pre-downloaded in a phase with no proxy attached,
  and the scans run with `--skip-db-update --skip-java-db-update`. Without the
  Java step, every Java image (languagetool, cloudbeaver, jenkins) returns a DNS
  error for `mirror.gcr.io` and is counted unscannable — measured, 2026-10-09.
- **A malformed `.prom` file makes node-exporter discard the whole file**, not
  just the bad line, so a formatting slip silently removes every metric in it and
  every alert that depends on it stops evaluating. `render_metrics` is tested for
  this and `TextfileCollectorError` alerts on `node_textfile_scrape_error`.
- **Status and data metrics live in separate files, and must not overlap.** The
  first version published `errors=0` in the data file too; when a collection
  failed, the preserved data file kept asserting `errors=0` while the status file
  said `errors=1`, and the exposition served the stale zero. The failure was
  hidden by its own fallback.
- **`.gitignore` has no effect on already-tracked files.** This is the usual
  reason a committed secret persists after someone thinks they fixed it; use
  `git rm --cached`, then rotate.
- **`.gitignore` entries for `.env` do not match `.env.bak`.** A copy made while
  debugging is genuinely committable while the original is safe, which is why
  both the hook and the scan peel backup suffixes before testing a filename.

## Trivy pin

Trivy runs as `TRIVY_IMAGE` in `security_scan.py` (tag + multi-arch index digest, never `:latest`). The code scan also SBOM-scans that image, so a fixable CVE in it alerts like any other image. A new release is not announced: check `docker buildx imagetools inspect aquasec/trivy:<new>` and replace the one constant with `aquasec/trivy:<new>@sha256:<Digest of the index>`, then `python3 test_security_scan.py` and `sudo systemctl start security-code-scan.service`.

## Known gaps

- **beefy's working-tree hygiene is not checked.** The filename check runs only
  against fastpi's clone. beefy's repo content *is* scanned, via the GitHub
  mirror, and its commit path is covered by the pre-commit hook - so the gap is
  specifically "a secret file sitting in beefy's working tree, uncommitted". The
  hook catches it the moment anyone tries to commit it.
- **New findings are diffed, the backlog is not.** `NewFixableImageVulnerability` fires per (image, CVE, package) first seen in 24 h. The first run and any image new to the scan are baselined (`vulns-seen-<scope>.json`), so a newly added image's backlog shows only in `code-cves-<repo>.txt` / `image-cves-<host>.txt` and `CriticalImageVulnerabilities`. Re-baseline: `rm /var/lib/security-scan/vulns-seen-<scope>.json`.
- **The code scan is daily (03:40), bounded by the Trivy DB**, republished about daily (~21:15 local): a new CVE shows by the next 03:40. The run matches cached SBOMs (`/var/lib/security-scan/sbom/`, rebuilt every 24 h, at most 20 Docker Hub + 100 others per run because of Docker Hub's rate limit) and never runs alongside the nightly image scan (shared Trivy cache).
- **No real-time intrusion detection.** rkhunter, chkrootkit and Lynis run weekly on fastpi and beefy (not tower: Unraid has no apt). Nothing watches continuously: no auditd or AIDE.
- **beefy and tower are only read when awake.** beefy is up 03:55 to about 04:45 (maintenance wake, then the window hold, then its idle watcher), so everything reading beefy runs between 04:00 and 04:45 (window: Server/6-Night-Schedule). When it is missed, its subjects go stale (`SecurityScanStale`: 48 h daily, 14 d for weekly subjects and Cup). tower subjects (and `ClamavScanStale` for tower) count only after tower was awake for a whole scan slot in the last 24 h (`tower:awake_for_scan`: 03:55-04:15 for logins/patches, 04:55-05:59 for av) and still have no result for 26 h, so a sleeping tower is silent.

## unattended-upgrades covers less than it looks like

Prepared, not installed: `apt/52unattended-upgrades-local` adds the Raspberry Pi archive (see [auto-updates.md](auto-updates.md#os-packages)).

Installed on both hosts, but its allowed origins are Debian/Debian-Security
only. fastpi also pulls from **Docker**, Raspberry Pi Foundation, Artifactory and
packagecloud/OpenTofu, and **none of those are auto-upgraded**.

This is deliberate: upgrading `docker-ce` restarts the Docker daemon and with it
every container on the host, which is not something to do unattended at 06:30.
The gap is covered by measurement rather than automation — `apt list
--upgradable` counts *all* origins, so `security_pending_updates` includes the
packages unattended-upgrades will never touch, and `PendingSecurityUpdates`
fires if they sit for three days. Auto-patch what is safe; alert on the rest.

## SSH / CrowdSec — deliberately not wired

**No CrowdSec on beefy or tower either** (decision 2026-10-19): SSH there is LAN-only too, and a CrowdSec agent per host is a moving part for logs with no attacks in them. Instead `security_failed_logins_total` counts failed logins on all three (fastpi journal, beefy `/var/log/auth.log`, tower `/var/log/syslog`) and `FailedLoginsSpike` (> 20 in 24 h, info) tells.

CrowdSec has the `crowdsecurity/sshd` collection **enabled but fed nothing**: its
only acquisition source is Traefik's access log. That is misleading, so it is
recorded here rather than left to be rediscovered.

It was left that way on purpose. Measured 2026-10-09:

- SSH is not reachable from outside — no port forward, no `ssh` ingress in the
  Cloudflare tunnel. Port 22 listens on `0.0.0.0` but only the LAN can reach it.
- fastpi: **0** failed SSH attempts in 7 days.
- beefy: **3** failures in the current `auth.log`, and all 4328 connection
  entries come from `192.168.1.2` — i.e. from fastpi, which is this automation.

fastpi has no rsyslog, so feeding the collection would mean installing a syslog
daemon to produce an `auth.log` for a log with no attacks in it. That is a new
moving part bought with nothing, so it was skipped.

**If SSH is ever exposed** (a port forward, or an `ssh` tunnel ingress), do this:

```bash
sudo apt-get install -y rsyslog            # fastpi; beefy already has it
```

then add to `Docker/CrowdSec/config/acquis.yaml`:

```yaml
---
filenames:
  - /var/log/auth.log
labels:
  type: syslog
```

and mount it read-only in `Docker/CrowdSec/docker-compose.yaml`:

```yaml
      - /var/log/auth.log:/var/log/auth.log:ro
```

The CrowdSec image has **no `journalctl`**, so the journald datasource is not an
option — an `auth.log` on disk is required.

## Files

| File | Purpose |
|---|---|
| `security_scan.py` | the scan; pure parsing seams + a thin I/O shell |
| `test_security_scan.py` | tests over the pure functions (`python3 test_security_scan.py`) |
| `security-scan.{service,timer}` | daily 04:05: secrets, patches (incl. tower Unraid), logins, cup |
| `security-av.{service,timer}` | daily 04:20 (beefy) + 05:40 + 05:50: av (with avhits), media, updates |
| `security-av-hits.{service,timer}` | every 15 min: avhits |
| `beefy-idle-pull.{sh,service,timer}` | every 5 min: copies beefy's `/run/beefy-idle.prom` (idle-watcher reasons) to `beefy_idle.prom`, removes it when beefy is down; feeds `BeefyAwakeLong`. Also copies beefy's queue-watchdog digest events (`~/.local/state/movie-downloads/watchdog-digest.prom`) to `beefy_watchdog.prom`, kept while beefy sleeps, for the daily digest. Also copies `storage.prom` -> `beefy_storage.prom` and the mover's `/var/lib/beefy-mover/mover.prom` -> `beefy_mover.prom` (same keep-while-asleep rule; feed the `Beefy*Filling/Full` and `BeefyMover*` alerts). Same rule for `/var/lib/smart-exporter/smart_beefy.prom` -> `smart_beefy.prom` (SMART alerts), `~/.local/state/movie-downloads/media-metrics.prom` -> `beefy_media.prom` and, once the popular job writes it, `~/.local/state/jellyfin-popular.prom` -> `beefy_jellyfin_popular.prom` (dashboard `homelab-morning`, `Docker/grafana/README.md`). Every copy is validated (at most 256 KiB, only that file's metric names, any `host` label must be `beefy`, `smart_*`/`indexer_*` need `host="beefy"`, no HELP/TYPE for them); one bad line rejects the file and the old copy stays. Test: `./test_beefy_idle_pull.sh` |
| `~/.ssh/config` `beefy-direct`, `tower-direct` (not in git) | same hosts without the WoL `Match` block; scans use them so an asleep host stays asleep. Plain `beefy` (may wake) only inside 04:00–04:30 (`BEEFY_WAKE_WINDOW`) |
| `security-image-scan.{service,timer}` | daily 04:10: images |
| `security-code-scan.{service,timer}` | daily 03:40: code |
| `security-dt.{service,timer}` | daily 04:02: dt |
| `../../Docker/_global/systemd/auto-update.{service,timer}` | daily 03:10: `auto_update.py` (installed by `install.sh`) |
| `auto-updates.md` | auto-update tiers, switches, risks, costs |
| `apt/52unattended-upgrades-local` | prepared unattended-upgrades addition |
| `security-audit.{service,timer}` | weekly Sun 04:05: audit (beefy first) |
| `install.sh` | idempotent installer |
| `install-audit-tools.sh` | rkhunter, chkrootkit, Lynis (CISOfy repo), rkhunter baseline |
| `../../.gitleaks.toml` | rules + triaged allowlists (repo root) |
| `../../.githooks/pre-commit` | blocks secrets at commit time |

Reports written for the alerts to point at, in `/var/lib/security-scan/`:
`hygiene-problems.txt`, `image-cves-<host>.txt`, `code-cves-<repo>.txt`, `vulns-seen-<scope>.json`, `gitleaks-<repo>.json`,
`last-infected-<host>.txt`, `audit-<host>.txt`, `audit-accepted-<host>-<tool>.txt`.

## Verify

```bash
python3 test_security_scan.py
python3 ../../Docker/_global/scripts/test_auto_update.py
systemctl list-timers 'security-*' auto-update.timer
docker exec prometheus wget -qO- http://node-exporter:9100/metrics | grep -E '^(security|clamav)_'
docker exec prometheus wget -qO- http://node-exporter:9100/metrics | grep '^node_textfile_scrape_error'   # must be 0
cd ../../Docker/grafana/prometheus && docker run --rm --entrypoint promtool -v "$PWD":/w -w /w/tests prom/prometheus:latest test rules antivirus_test.yml security_test.yml auto-updates_test.yml weekly-digest_test.yml weekly-digest-dst_test.yml
```
