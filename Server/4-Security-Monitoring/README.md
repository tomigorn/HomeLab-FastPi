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
| Who logged in over SSH (sshd is key-only, so no failures)? | `access` | accepted logins in the last 24 h by user and source class (lan 192.168.1.0/24, vpn 172.24.255.5 + 10.8.0.0/24, tunnel 172.20.0.0/16 = cloudflared, other); alerts on non-lan or a user other than `pi` | fastpi | every 5 min (`security-access.timer`, root) |
| Did authorized_keys, sudoers or sshd_config change? | `access` | SHA-256 of `/home/*/.ssh/authorized_keys`, `/root/.ssh/authorized_keys`, `/etc/sudoers`, `/etc/sudoers.d/*`, `/etc/ssh/sshd_config(.d/*)` against a baseline | fastpi | every 5 min |
| Image updates per host? | `cup` | Cup's JSON per `server`; refreshes Cup first when beefy or tower is awake (once per run; a host that is off is reported as skipped, not as an error) | all three | daily 04:05 |
| Malware? | `av` | pulls the ClamAV results of the nightly scans (`Docker/antivirus`; beefy 04:05, fastpi and tower 05:00) | all three | daily 04:20 (beefy), 05:40, 06:40 |
| Are container images vulnerable? | `images` | Trivy across the images actually running | all three | weekly 04:10 daily |
| Rootkit / hardening? | `audit` | rkhunter, chkrootkit, Lynis | fastpi, beefy | weekly Sun 04:05 |
| Tagged titles still without their audio language (not security, same pull) | `media` | beefy's `media-language.prom` (Movie-Downloads `language-missing.py`), republished as `media_language_beefy.prom`; alert `AudioLanguageNotFound` (`grafana/prometheus/rules/media-language.yml`) | beefy | daily 04:20, 05:40, 06:40 (with `av`) |
| Everything in one message | - | `WeeklyUpdateDigest` alert (`grafana/prometheus/rules/weekly-digest.yml`) | - | Mon 05:00 local |

Metrics:

| Metric | Labels |
|---|---|
| `security_failed_logins_total` | host |
| `security_ssh_logins`, `security_ssh_last_login_timestamp_seconds` | host, user, source_class |
| `security_integrity_changed` (1 = changed, new or missing), `security_integrity_file_info` (12-hex hash prefix), `security_integrity_files` | host, path / + sha256_prefix / host |
| `security_unraid_os_update`, `security_unraid_plugin_update` | installed, available / plugin |
| `security_image_updates`, `security_image_update_info` | host, type / host, reference, type |
| `clamav_*` (republished as `clamav_<host>.prom`, beefy's hook as `clamav_hook_beefy.prom`), `security_av_infected_info` | host, mode / host, path, signature |
| `security_rootkit_warnings` (new), `security_rootkit_findings` (all) | host, tool |
| `security_lynis_hardening_index`, `security_lynis_warnings` | host |
| `media_language_missing_since_timestamp_seconds`, `…_notify_timestamp_seconds` (republished from beefy) | app, title, language, failed |

Everything lands as Prometheus metrics via node-exporter's textfile collector
and alerts through `grafana/prometheus/rules/security-posture.yml`, `antivirus.yml`
and `weekly-digest.yml` → Alertmanager → email + Telegram (severity info = Telegram
only). Dashboard: **Grafana > fastpi > Updates & security**,
https://grafana.holy-grail.ch/d/updates-security. There is no second notifier and no
second place the Telegram token lives.

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

**Rootkit checkers report against a baseline.** Both tools flag known false positives on a stock system (on beefy, Ubuntu 26.04's uutils coreutils reads as INFECTED to chkrootkit). The first run accepts what it finds, like `rkhunter --propupd`; `security_rootkit_warnings` counts only findings not in `/var/lib/security-scan/audit-accepted-<host>-<tool>.txt`. chkrootkit findings are its WARNING headers and INFECTED lines, not the paths listed under a header (those change every run: `/proc/<pid>`, scripts in `/tmp`). Report: `audit-<host>.txt`, NEW marks unaccepted findings. Accept again:

```bash
rm /var/lib/security-scan/audit-accepted-<host>-<tool>.txt && sudo systemctl start security-audit.service
```

**Accept a changed authorized_keys / sudoers / sshd_config.** `SecurityFileChanged` clears only when the baseline (`/var/lib/security-scan/integrity-baseline-fastpi.json`, written by the first run) is re-accepted after you checked the change:

```bash
sudo rm /var/lib/security-scan/integrity-baseline-fastpi.json && sudo systemctl start security-access.service
```

Login alerts (`SshLoginOutsideLan`, `SshLoginUnexpectedUser`) stay up for an hour after the login. The `access` group runs as root in its own 5-minute unit because sudoers and other users' keys are root-only; it is read-only apart from the two state/metric directories. The leftover `deploy` user's key is in the baseline, so a login by it alerts.

**The audit unit is not sandboxed.** It runs the tools via sudo and they must see the real system (PrivateTmp/ProtectHome would hide what chkrootkit looks at).

**MalwareFound is "last run had hits"**, `max by (host) (clamav_infected_last_run) > 0` over every mode (new, all, path, hook), not `increase()` of the counter: a counter reset (the EICAR test) read as a hit. It clears with the next clean run of that mode. `for: 45m`, so the 04:20 (beefy) or 05:40 pull has put the hit list (`security_av_infected_info`, max 20) into the description first. A missing remote `clamav.prom` is "no data": old file kept, no error.

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

## Known gaps

- **beefy's working-tree hygiene is not checked.** The filename check runs only
  against fastpi's clone. beefy's repo content *is* scanned, via the GitHub
  mirror, and its commit path is covered by the pre-commit hook - so the gap is
  specifically "a secret file sitting in beefy's working tree, uncommitted". The
  hook catches it the moment anyone tries to commit it.
- **Trivy counts, not diffs.** The alert is on an absolute CVE count, which is a
  backlog figure. A newly published CRITICAL in an image that already had some
  will not stand out. `image-cves-<host>.txt` is the thing to read.
- **No real-time intrusion detection.** rkhunter, chkrootkit and Lynis run weekly on fastpi and beefy (not tower: Unraid has no apt). Nothing watches continuously: no auditd or AIDE.
- **beefy and tower are only read when awake.** beefy is up only 03:55 to about 04:26 (maintenance wake, then its idle watcher), so everything reading beefy runs between 04:00 and 04:25. When it is missed, its subjects go stale (`SecurityScanStale`: 48 h daily, 7 d for tower, 14 d for weekly subjects and Cup).

## unattended-upgrades covers less than it looks like

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
| `test_security_scan.py` | 112 tests over the pure functions (`python3 test_security_scan.py`) |
| `security-scan.{service,timer}` | daily 04:05: secrets, patches (incl. tower Unraid), logins, cup |
| `security-av.{service,timer}` | daily 04:20 (beefy) + 05:40 + 06:40: av |
| `security-image-scan.{service,timer}` | weekly 04:10 daily: images |
| `security-audit.{service,timer}` | weekly Sun 04:05: audit (beefy first) |
| `install.sh` | idempotent installer |
| `install-audit-tools.sh` | rkhunter, chkrootkit, Lynis (CISOfy repo), rkhunter baseline |
| `../../.gitleaks.toml` | rules + triaged allowlists (repo root) |
| `../../.githooks/pre-commit` | blocks secrets at commit time |

Reports written for the alerts to point at, in `/var/lib/security-scan/`:
`hygiene-problems.txt`, `image-cves-<host>.txt`, `gitleaks-<repo>.json`,
`last-infected-<host>.txt`, `audit-<host>.txt`, `audit-accepted-<host>-<tool>.txt`.

## Verify

```bash
python3 test_security_scan.py
systemctl list-timers 'security-*'
docker exec prometheus wget -qO- http://node-exporter:9100/metrics | grep -E '^(security|clamav)_'
docker exec prometheus wget -qO- http://node-exporter:9100/metrics | grep '^node_textfile_scrape_error'   # must be 0
cd ../../Docker/grafana/prometheus && docker run --rm --entrypoint promtool -v "$PWD":/w -w /w/tests prom/prometheus:latest test rules antivirus_test.yml security_test.yml weekly-digest_test.yml weekly-digest-dst_test.yml
```
