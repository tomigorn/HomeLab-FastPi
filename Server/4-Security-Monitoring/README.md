# Security monitoring

Four security questions, answered on a schedule and routed into the alerting
pipeline that already exists:

| Concern | What answers it | Cadence |
|---|---|---|
| Are any secrets public? | gitleaks over the published GitHub history of both repos | daily 04:12 |
| Could a secret become public? | filename hygiene check + a pre-commit hook | daily / every commit |
| Is the OS patched? | `apt list --upgradable`, security updates counted separately | daily 04:12 |
| Are container images vulnerable? | Trivy across the images actually running | weekly Sun 04:20 |

Everything lands as Prometheus metrics via node-exporter's textfile collector
and alerts through `grafana/prometheus/rules/security-posture.yml` → Alertmanager
→ email + Telegram. There is no second dashboard, no second notifier and no
second place the Telegram token lives.

## Install

```bash
./install.sh          # on fastpi; idempotent
```

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

**Trivy reads images through the read-only socket proxy** (`POST=0`), which each
host already runs for Cup and telegraf. Trivy is not made a new Docker socket
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
- **No runtime intrusion detection.** This answers "what is vulnerable" and
  "what is exposed", not "is something running that should not be". There is no
  auditd, AIDE or rkhunter here.

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
| `test_security_scan.py` | 36 tests over the pure functions (`python3 test_security_scan.py`) |
| `security-scan.{service,timer}` | daily: secrets, hygiene, patches |
| `security-image-scan.{service,timer}` | weekly: Trivy |
| `install.sh` | idempotent installer |
| `../../.gitleaks.toml` | rules + triaged allowlists (repo root) |
| `../../.githooks/pre-commit` | blocks secrets at commit time |

Reports written for the alerts to point at, in `/var/lib/security-scan/`:
`hygiene-problems.txt`, `image-cves-<host>.txt`, `gitleaks-<repo>.json`.

## Verify

```bash
python3 test_security_scan.py
systemctl list-timers 'security-*'
curl -s localhost:9100/metrics | grep '^security_'
curl -s localhost:9100/metrics | grep '^node_textfile_scrape_error'   # must be 0
```
