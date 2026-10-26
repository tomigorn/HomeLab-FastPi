# Auto-updates and fast CVE detection

**Verdict:** auto-update yes, but by tier, not "everything". Stateless stacks: auto, with a cool-down, a functional check and automatic rollback. Stateful / DB-migrating stacks and the edge: detect within the hour, notify with the exact command, a human applies. Reason: a rollback can only undo an image, not a one-way data migration, and the edge is what every other check (and your access) runs through.

## What runs

| Piece | When | What | State |
|---|---|---|---|
| `security-code-scan.timer` → `security_scan.py code` | daily 03:40 | every image the two repos refer to (compose `image:` with `${VAR}` from `.env`/`.env.example`, Dockerfile `FROM`; local builds left out, their bases scanned) → cached CycloneDX SBOM per image → `trivy sbom` against the current DB | **enabled** |
| `security-image-scan.timer` → `images` | 04:10 | running digests on fastpi, beefy, tower (registry copy, no pull on tower) | existed; now also diffs findings |
| `NewFixableImageVulnerability` | on a new finding | one Telegram per batch of fixable CRITICAL/HIGH (image, CVE, package) first seen in 24 h, either scan | **enabled** |
| `auto-update.timer` → `Docker/_global/scripts/auto_update.py` | 03:10 | tiers in `Docker/_global/auto-update.conf` | **enabled** (auto tier) |
| beefy: same script, own `auto-update.conf` | 04:12 | see [beefy](#beefy) | **enabled** (auto tier) |
| `AutoUpdateNightly` | hour after the run | one Telegram per host (`host` label): updated / rolled back / available (with command) / errors; capped at ~3000 characters (failures first), the rest becomes `… N more, see journalctl -u auto-update` (Telegram limit 4096) | **enabled** |
| `AutoUpdateRollbackFailed` | at once | email + Telegram; the script also pages via `oob-alert.sh` (bypasses the edge) | **enabled** |
| unattended-upgrades | daily (apt timers) | Debian + Debian-Security only, no reboot | existed |
| `crowdsec-autoupdate.timer` | 05:07 | CrowdSec engine patch/minor + hub, own verify/rollback | existed |

## Tiers (`Docker/_global/auto-update.conf`)

| Tier | Projects | Behaviour |
|---|---|---|
| `auto` | Claude-Mockups, M4b-Merge-Dashboard, DDNS, sbb-easyride-taxreport | new digest of the tag in the repo → wait `COOLDOWN_HOURS` (24) → pull → refuse a major jump (OCI version label) → `update-project.sh recreate` (container verify + `CHECK` command) → rollback on failure; a rolled-back digest is held until the tag moves again |
| `notify` | audiobookshelf, Home-Assistant, grafana (Prometheus, InfluxDB, Grafana DB), mouse, antivirus autoheal, Docker-Socket-Proxy, Portainer, Cup | Telegram with the exact `update-project.sh … pull <backups>` command; nothing pulled |
| `edge` | Authentik, Traefik, adguard, cloudflared, WireguardVPN | like notify (machine.md: owner's yes) |
| `edge-auto` | cloudflared, adguard (owner 2026-10-25) | like auto, check = canary / DNS / public route; failed rollback → OOB page |
| not listed | LoyaltyCards*, bitwarden (parked), CrowdSec (own updater), local builds, tower | untouched |

Only the digest behind the tag written in the repo moves, so the repo stays the truth. Version bumps of pinned tags (`v3.15.1` → `v3.16.0`) stay with Cup + the Monday digest: they need a repo edit.

## Switches

| Action | Command |
|---|---|
| Enable the edge for one stack (not Authentik: it migrates its DB) | in `auto-update.conf` change `edge` to `edge-auto` on its line |
| Move a stack between tiers | edit its line (`auto` / `notify`) |
| Cool-down | `Environment=COOLDOWN_HOURS=24` in `Docker/_global/systemd/auto-update.service`, then `sudo install -m644 … /etc/systemd/system/ && sudo systemctl daemon-reload` |
| Pause | `sudo systemctl disable --now auto-update.timer` |
| Dry run | `python3 Docker/_global/scripts/auto_update.py --dry-run [project]` (needs write access to `/var/lib/auto-update`: run as the service, or set `AUTO_UPDATE_STATE`/`AUTO_UPDATE_TEXTFILE` to a scratch dir) |
| Rollback drill | `TEST_FORCE_FAIL=1 CHECK='…' Docker/_global/scripts/update-project.sh <dir> recreate` → `ROLLED BACK`, exit 1 |
| Log | `journalctl -u auto-update` ; backups in `~/backups/pre-update/<date>/<project>/` |

## Risks and mitigations

| Risk | Mitigation here | Left open |
|---|---|---|
| Breaking change in a new image | stateless stacks only; functional check; automatic rollback; never across a major (OCI version label) | an image without a version label can still jump a major under `:latest` |
| One-way DB migration | stateful stacks are `notify`; the command backs up first | the human still has to read the release notes |
| Compromised tag / registry account (supply chain) | 24 h cool-down (a hijacked tag is often noticed and replaced within hours to days); digest recorded per night (old → new in the summary); hourly CVE scan of the new digest | no signature/provenance check (cosign) yet; the cool-down is a delay, not a proof |
| Tooling itself (Trivy) | pinned by tag + multi-arch digest in `TRIVY_IMAGE` (`security_scan.py`); runs without socket access in the remote mode; the hourly code scan SBOM-scans the pinned image itself, so a fixable CVE in it raises `NewFixableImageVulnerability` | newer releases are not announced (Cup only sees running containers): bump by hand, steps in the Security README |
| Edge break locks you out | edge stays notify; `edge-auto` pages over `oob-alert.sh` (direct Telegram, DoH) | the owner decides per stack |
| Exploit faster than the cool-down | `notify` + hourly detection tell you within an hour of the DB update; apply by hand | `COOLDOWN_HOURS` is a trade-off you set |

## Costs (measured 2026-10-24 on fastpi)

| Item | Cost |
|---|---|
| Hourly code scan, steady state | ~30 s, ~1 s CPU; no registry traffic except up to 4 Docker Hub + 12 other SBOM rebuilds/h (each SBOM refreshed daily) |
| First SBOM fill (≈70 refs) | ~1.5 min per 16 images; complete within ~a day at the hourly budget |
| Trivy DB | 130 MB download, only when stale (published about daily, ~21:15 local): new CVEs show within an hour of that instead of at 04:10 next day |
| Nightly auto-update | ~2 min for ≈40 refs (3 s pacing) + ~1 min per applied update |
| Docker Hub | 100 manifest requests/h per account (header `ratelimit-limit: 100;w=3600`) and 429 on bursts — hit at 02:39 tonight by repeated test runs; the pacing + SBOM budget keep a normal night far below |
| RAM / disk floor | nothing pulls or builds SBOMs below 1200 MB available or 20 GB free |

## Can a scanner see components from the code?

| Source | Recognised | Note |
|---|---|---|
| compose `image:` | yes (here: own parser) | Trivy has no compose support; `${VAR}` needs `.env` (fastpi) or `.env.example` (beefy mirror) |
| Dockerfile `FROM` | yes | the base, not what `RUN apk add` installs: local builds are only as good as their base scan |
| lockfiles (`package-lock.json`, `requirements.txt`, `go.sum`) | yes, `trivy fs` | none of the stacks here ship app code with a lockfile worth it; not wired |
| misconfig (`trivy config`) | Dockerfile yes, compose no | noisy (USER, HEALTHCHECK); skipped |
| secrets | yes | gitleaks over the published history already does this daily |

A tag in the code is not a version: `:latest` / `:stable` resolve to whatever the registry has today, so the code scan answers "what would I get", the nightly scan "what runs".

## OS packages

| Host | Now | Recommendation |
|---|---|---|
| fastpi (Debian 13 trixie, since 2026-10-25) | unattended-upgrades on, Debian + Debian-Security + Raspberry Pi archive (installed 2026-10-25, `/etc/apt/apt.conf.d/52unattended-upgrades-local`), no reboot | a new kernel/firmware waits for the next attended reboot; keep Docker/HashiCorp/OpenTofu manual |
| beefy | unattended-upgrades installed (Debian/Ubuntu defaults) | review in the beefy repo |

Install the prepared file (attended, does not run apt):

```bash
sudo install -m 0644 Server/4-Security-Monitoring/apt/52unattended-upgrades-local /etc/apt/apt.conf.d/
sudo unattended-upgrade --dry-run --debug 2>&1 | grep -i 'allowed origins'
```

## beefy

Same `auto_update.py`, `test_auto_update.py`, `update-project.sh`: verbatim copies in beefy's `Docker/_global/scripts/` (change them here, run the tests, copy). Host differences come from the unit's environment and the script's location. beefy repo README "Image auto-update".

| Item | beefy |
|---|---|
| When | 04:12 (inside the 03:55–04:45 window, after the 04:05 scan); `AUTO_UPDATE_APPLY_BY=04:16`: nothing starts later, the rest is `deferred` to the next night; `AUTO_UPDATE_MAX_APPLY=2` projects a night; `TimeoutStartSec=600` hard stop. No wake of its own |
| auto | Movie-Downloads flaresolverr, recyclarr, vpn-status; Cup-Agent cup-agent, socket-proxy-unix (pinned tags except socat) |
| notify | socket proxies + autoheal (docker.sock), gluetun + *arr + qBit + SAB (state; gluetun carries the VPN namespace), Seerr (pinned by digest), Ryot + ryot-db, Portainer-Agent; Jellyfin, clamav, ryot-go are local builds (`local_build`, detected from compose `build:`) |
| Keep-awake | the unit holds `beefy-keep-awake` while it runs and releases only its own hold |
| Docker | the unit has the `docker` group; by hand (`buntu`) both scripts fall back to `sudo -n docker` |
| Result | `/var/lib/auto-update/textfile/auto_update.prom` → `security_scan.py updates` (security-av, 04:20) → `auto_update_beefy.prom` here (only `host="beefy"` samples) → `AutoUpdateNightly{host="beefy"}` |
| Out-of-band page | none on beefy (no Telegram secret there): `AutoUpdateRollbackFailed` is the page, after the 04:20 pull |
| Docker Hub | beefy and fastpi share one public IP, so one 100 requests/h budget: the runs are an hour apart |

## Not covered yet

- Local builds (`build --pull` of Avatar-Picker, Stonks, wakers …): base-image CVEs are detected, rebuilds stay manual.
- Pinned version bumps: Cup + Monday digest, by hand.
