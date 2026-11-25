# _global/scripts

| Script | What |
|---|---|
| `docker-user-lan-guard.sh [--persist]` | DOCKER-USER: which containers may reach the LAN (FORWARD) |
| `host-input-guard.sh [--persist]` | HOST-GUARD/HOST-GUARD6: which containers / VPN peers may reach the host itself (INPUT); HOST-LAN-GUARD: LAN allow-list on eth0/wlan0 (D-02) |
| `host-output-guard.sh [--persist]` | HOST-OUT-GUARD: what the host itself (incl. host-network containers) may open on beefy (OUTPUT) |
| `iptables-persist.sh` | writes `/etc/iptables/rules.v4/v6` with only those chains; never `netfilter-persistent save` |
| `smoke-test.sh` | end-to-end checks, must stay green |
| `unpinned.sh` | stdin: `docker inspect` JSON; lists `name/network` without a fixed IPv4 (used by smoke-test, test: `test_unpinned.sh`) |
| `update-project.sh`, `auto_update.py` | image updates (`UPDATE-RUNBOOK.md`, rollback restores compose/.env, old image and, after an image change, the data backups; a failed build or backup aborts before the recreate; an unknown name in `SERVICES` aborts first (exit 2, valid names listed); `build: network: host` services are built by `buildx bake --allow=network.host`; backups owner-only; bind-path backups use `sudo tar`, so they work by hand but not under `auto-update.service` (NoNewPrivileges): auto rows back up volumes only). Drift (container ref/id ≠ compose's declared ref) and shared tags: see below. `-h`/`--help` or an unknown option prints usage and does nothing (also `rebuild_local.py`, `image-cleanup.sh`, `security_scan.py`). Test: `./test_update_project.sh`, `python3 test_auto_update.py` |
| `rebuild_local.py` | weekly rebuild of the local images with tests and rollback (`Server/4-Security-Monitoring/auto-updates.md` "Local builds", list `../rebuild-local.conf`). Images without a shell (scratch) are compared by a content digest of their filesystem (mtimes ignored) instead of the package list. Test: `python3 test_rebuild_local.py` |
| `migrate-rollback-tags.sh` | one-shot: old `<repo>:rollback-*` tags -> `rollback.invalid/` (tags only). Test: `./test_migrate_rollback_tags.sh` |
| `oob-alert.sh` | Telegram alert that bypasses the edge; `--check` proves the path without sending (batch start), `--test` sends a 🧪 message (to `TEST_CHAT_ID` in `oob-alert.env` if set, else the alert chat). Test: `./test_oob_alert.sh` |
| `maintenance-silence.sh on [hours] [reason] \| off \| status` | Alertmanager silence for batch/upgrade work (crash loops, container down/unhealthy, file changes, reboots, own SSH logins), default 4 h, max 24 h; only touches its own silences. Test: `./test_maintenance_silence.sh` |
| `subscription-alerts.py` | Telegram warnings for the due dates (`../Due-Dates`), see below |
| `mam-points.py` | MyAnonamouse bonus-points estimator + Telegram warnings, see below |
| `customization_check_exporter.py` | runs `post-update-check.sh all` and counts `port_updater` reattaches every 2 h, publishes to Prometheus, see below |
| `ctest.sh` | throwaway test container that cannot change anything, see below |
| `policy_check.py` | container rules as a check over every compose project, exceptions in `../policy-exceptions.toml`, see below |
| `repo_drift.py` | nightly repo-vs-live compare (compose, units, scripts, /etc, uncommitted files), metric `drift_items{host,kind}`, see below. Test: `python3 test_repo_drift.py` |
| `arch_page.py` | generates the notes page `homelab-architecture.md` (all containers of fastpi, beefy, tower), see below |

## policy-check
`policy_check.py`: the container rules (`docs/container-hardening.md`, `CLAUDE.md`) as a check over every compose project under `Docker/`. Same file on fastpi and beefy: keep them identical.

| Rule | Violated when |
|---|---|
| `ipv4_address` | a network without a fixed `ipv4_address` (`network_mode` host/none/container:/service: skipped) |
| `user` | `user:` missing, root/0, uid or gid 1000, gid 100 |
| `user_unique` | the uid is also used in another project folder (sharing inside one project is fine) |
| `cap_drop` | `cap_drop` without `ALL` (`cap_add` is fine) |
| `no_new_privileges` | no `security_opt: no-new-privileges:true` |
| `healthcheck` | no compose healthcheck and none in the image (`docker image inspect`), or `disable: true` |
| `image_pinned` | no tag or `latest`, without digest; `build:` and `*-local` / `:local` images skipped |
| `env_secret` | env name with PASSWORD/SECRET/TOKEN/KEY and a plain value (also from `.env`); `*_FILE`/`_PATH`/`_URL`, paths, URLs, true/false/numbers skipped. Values are never printed |

| | |
|---|---|
| Run | `python3 Docker/_global/scripts/policy_check.py [PROJECT ...]` (all by default); prints `project/service: rule (detail)`, exit 0 clean, 1 violation or stale exception, 2 error |
| Stacks | `docker-compose.yaml` (+ `.override.yaml`); a `docker-compose.<v>.yaml` is its own stack `<Project>:<v>`; all profiles |
| Exception | add to `Docker/_global/policy-exceptions.toml`, reviewed like code; remove it with the fix (a stale entry fails):<br>`[[exception]]` `project = "Traefik"` `service = "traefik"` `rule = "healthcheck"` `reason = "…"` (all four required) |
| Wired | `smoke-test.sh`: one line per host (gate). `post-update-check.sh <Project>`: `== policy (report only)`, never fails or rolls back an update; skipped for `all` |
| Completion | `source Docker/_global/scripts/completions/policy_check.bash` (bash) |
| Test | `python3 test_policy_check.py` |

## customization-check
Closes the gap that `post-update-check.sh` and `smoke-test.sh` only run by hand: on 2026-11-06 a broken gluetun network went 13 h without an alert.

| | |
|---|---|
| When | `customization-check.timer`, 00:11 and every 2 h 06:11-22:11 Europe/Zurich (not during the DST hour or the 03:10-05:50 nightly jobs). A run takes ~70 s, 12 s CPU |
| Metrics | `customization_check_failed{id}` (failed ids only, never check output), `customization_checks_failed`, `customization_checks_passed`, `port_updater_reattaches_6h`, `port_updater_stack_restarts_6h` (`docker logs --since 6h`), `customization_check_last_success_timestamp_seconds{collector}`, `customization_check_errors{collector}` |
| Files | `customization_checks.prom`, `port_updater_reattaches.prom`, each with `_status.prom`; a failed collection keeps the old data |
| Alerts | `grafana/prometheus/rules/customization-checks.yml`: `CustomizationCheckFailing` (two failing runs in a row, up to ~4 h 15 min after the fault), `PortUpdaterReattachLoop` (>= 2 reattaches or >= 4 stack restarts in 6 h), `CustomizationCheckStale` (> 8 h). All warning: Telegram, muted 22:00-07:00 |
| Sandbox | no `NoNewPrivileges` (checks use `sudo -n`), `ProtectSystem=strict` also holds under sudo |
| Sleeping hosts | never wakes beefy or tower; checks that depend on them pass with a note (`beefy asleep`, `beefy off at last refresh`, `*-tower` stale subjects) |
| Side effects | refused or read-only requests only; `wiki`, `notes`, `server-specs` probes overwrite one file in their container's `/tmp` |
| Install | `sudo install -m 0644 ../systemd/customization-check.{service,timer} /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now customization-check.timer` |
| Test | `python3 test_customization_check_exporter.py` |

## host-input-guard
- New host port needed by a container or the VPN: add it to the port lists in the script, `sudo ./host-input-guard.sh --persist`.
- Something from a container to the host times out: `sudo journalctl -k | grep 'host-guard drop'`.
- Remove the OUTPUT guard: `sudo iptables -D OUTPUT -d 192.168.1.102/32 -j HOST-OUT-GUARD`, then `sudo ./iptables-persist.sh`. Something on the host can't reach beefy: `sudo journalctl -k | grep 'host-out-guard drop'` (shows UID).
- Remove (one command): `for i in docker0 br-+; do sudo iptables -D INPUT -i $i -j HOST-GUARD; done; for i in eth0 wlan0; do sudo iptables -D INPUT -i $i -j HOST-LAN-GUARD; done; for i in docker0 br-+ eth0; do sudo ip6tables -D INPUT -i $i -j HOST-GUARD6; done`, then `sudo ./iptables-persist.sh`.

## image-cleanup
| | |
|---|---|
| What | `image-cleanup.sh`: removes images no container (running or stopped) uses, and build cache, both after 14 days. Never volumes, networks or containers. |
| When | weekly `image-cleanup.timer`: fastpi Sun 05:30, beefy Sun 04:20 (inside the maintenance wake, never a wake of its own). Install: `_global/install-image-cleanup.sh` |
| Unused clock | own state `/var/lib/image-cleanup/first-seen` (image ID, first seen unused). `prune --filter until` dates by build time, which would delete an image the day it was superseded |
| Rollback | `update-project.sh` tags the previous image `rollback.invalid/<repo>:<date>-<project>` (UPDATE-RUNBOOK.md "Rollback tags"), so a superseded image stays 14 days. Those tags (and old `<repo>:rollback-*` ones): kept 14 days from the date in the tag (else the tag time), then cleaned; only the newest `ROLLBACK_KEEP` (3, as in update-project.sh) per repo and project. Kept always: images of any container, other tags containing `rollback`, images referenced in the repo's compose files and scripts. First run: dangling images and older tags of a repo in use start their 14 days then |
| Referenced | whole word only (`influxdb:2.9` is not `influxdb:2.9.1`). `repo:${VAR}` and a bare repo name (for `:latest`) only protect repositories no container uses (scanners, on-demand tools); for a repository in use its other tags are old tags and go |
| Metrics | `docker_image_cleanup_{freed_bytes,removed_images,rollback_window_images,failed_images,last_run_timestamp_seconds}` in `image_cleanup.prom` |
| By hand | `scripts/image-cleanup.sh --dry-run` lists what would go and, as `pending`, what goes later with its date; `systemctl start image-cleanup.service` runs it (`KEEP_DAYS=7` env to change the age) |
| Test | `scripts/test_image_cleanup.sh` (fake docker) |

## Drift
A container created from another ref than the compose file declares (e.g. `alpine/socat:latest` while compose pins `alpine/socat:1.8.1.3@sha256:…`), or a digest pin running another image id.

| | |
|---|---|
| Check | `auto_update.py` reads the declared refs from `docker compose config` (compose + `.env`) and checks only those against the registry; a drifted container is result `drift` (🔁, with `SERVICES=… update-project.sh <dir> recreate`), never `available` |
| Fix | `auto`/`edge-auto` rows: recreated through `update-project.sh recreate` (checks, rollback) → `recreated` (♻️); a rollback is not retried for that image (state `drift_bad`). `notify`/`edge`: reported only |
| Shown | `AutoUpdateNightly` and the daily digest Auto-updates line (🔁 / ♻️) |

## Shared tags
When one project pulls a newer image under a tag others use too (`caddy:alpine`, `python:3.15.2-alpine3.24`), compose leaves the others on the old image.

| | |
|---|---|
| By hand | `update-project.sh` prints `shared tag: <ref> also runs in <container> (<project>/<service>) …` with the recreate command after a successful run |
| Nightly | `auto_update.py` recreates them through `update-project.sh <dir> recreate` (verify, rollback) when their row is `auto`/`edge-auto` and the service is in it; others are only logged. A major jump is held; a recreate that rolls back holds that tag (state `stale_bad`) |
| Metric | `container_image_stale{host,project,service,container,image,running,tag,dir}`, `container_image_stale_containers`, `container_image_stale_last_run_timestamp_seconds` in `container_image_stale.prom`, written by every run and by `auto_update.py --stale-only`; beefy's republished by `security_scan.py updates` |
| Alerts | `grafana/prometheus/rules/image-drift.yml`: `ContainerImageStale` (30 min), `ContainerImageStaleCheckMissing` (> 2 days) |

## subscription-alerts
| | |
|---|---|
| What | `subscription-alerts.py`: reads `/var/lib/due-dates/due-dates.json` (`../Due-Dates`: subscriptions, domains, No-IP, tokens, reminders), items with `alert = "telegram"`, sends Telegram via `oob-alert.sh`. `lifetime = true` never alerts. Domains get the registrar how-to, No-IP the confirm how-to, others their `howto` |
| Stages | from the item's `lead` days: default 🟡 ≤ 30 days left, 🟠 ≤ 7 days, 🔴 on the end date, 🔴 the day after ("expired yesterday"); No-IP 5 / 3 / 1 / 0; `kind = "reminder"` says "due". Same colours as the Seerr bar. Items on the same date and stage share one message |
| Once | each stage once per (title, date) in `/var/lib/subscription-alerts/state.json`. Renewal = change the date: the new date starts fresh, the old date's warnings are dropped. First run late (e.g. 23 days left) sends only the current stage. A failed send is retried at the next run |
| When | `subscription-alerts.timer` daily 05:37 Europe/Zurich (low-power hours, outside the DST hour and the nightly jobs), 5 min after boot, catch-up if missed. fastpi only, never asks beefy |
| List age | the list's `generated` time; older than 7 days (due-dates build failing): logged and said in the message details. The old `/var/lib/subscription-alerts/limits.toml` cache is no longer read |
| Install | `sudo install -m 0644 ../systemd/subscription-alerts.{service,timer} /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now subscription-alerts.timer` |
| By hand | `systemctl start subscription-alerts.service` then `journalctl -u subscription-alerts -n 5`; `scripts/subscription-alerts.py --test` sends one 🧪 test message |
| Renew | change the date in `Docker/Due-Dates/due-dates.toml` and commit (list rebuilt within 10 min; to force: `systemctl start due-dates.service subscription-alerts.service`) |
| Test | `python3 scripts/test_subscription_alerts.py` |

## ctest
| | |
|---|---|
| What | `ctest.sh [-v HOST_DIR[:CONTAINER_DIR]]... [-w DIR] [-e NAME=VALUE]... [--entrypoint CMD] IMAGE [ARG...]`: one-off test run, safe to allow without a prompt |
| Always | `--rm`, `--network=none`, `--read-only`, `/tmp` tmpfs 256 MB, user 65534, `--cap-drop=ALL`, `no-new-privileges`, `--pull=never` (only local images), 1 GB RAM, 2 CPUs, 256 pids |
| Mounts | read-only only, resolved path must be under `~/Projects` or `~/Documents/development` (home from passwd, not `$HOME`); symlinks out, the docker socket and any other option are refused. `CTEST_ROOTS` only counts for a copy the caller owns (tests) |
| Timeout | `CTEST_TIMEOUT` seconds (default 600, max 900), then the container is killed, exit 124; a killed caller kills it too |
| Installed | root-owned copy `/usr/local/libexec/fastpi/ctest.sh` (`../install-root-scripts.sh`, drift check `host.root-scripts`), so an agent editing the repo file cannot widen what the allow rule permits |
| Example | `bash /usr/local/libexec/fastpi/ctest.sh -v ~/Projects/Docker/grafana/prometheus:/p -w /p --entrypoint promtool prom/prometheus:v3.16.0 test rules tests/backup_test.yml` |
| Allow | `Bash(bash /usr/local/libexec/fastpi/ctest.sh *)` (only the root copy, never the repo path) |
| Test | `./test_ctest.sh` (fake docker) |

## mam-points
| | |
|---|---|
| What | `mam-points.py` (CLI `mam-points` → `~/.local/bin`): estimates the MyAnonamouse bonus points from the last known balance + rate. **No call to MAM** (its rules forbid automating unlisted endpoints) |
| Estimate | `min(99999, points + rate × hours since update)` |
| Commands | `mam-points status` · `set 51655 [--rate 309.9]` (current balance) · `spent 25000` · `reset` (= set 0) · `rate 309.9` (new points/hour) · `check [--preview]` (timer; `--preview` sends one sample 🟡 with made-up points) |
| Epoch | `set`, `spent`, `reset`, `rate` each start a new epoch; a new balance below 90,000 ends the daily alerts (`rate` keeps the balance, so they go on) |
| Alerts | 🟡 estimate ≥ 90,000 (days until the cap), 🔴 ≥ 99,999 (points wasted), **every day** until a new epoch, at most one per day (Zurich date, `last_alert` in the state). Both reached: only 🔴. Each message ends with `mam-points set <balance> --rate <points/hour>`. A failed send retries on the next run |
| Input | balance 0–99,999, spent > 0 and ≤ estimate, rate > 0; `51,655` accepted |
| State | `/var/lib/mam-points/state.json` (owned by `pi`, created by the unit's `StateDirectory`) |
| When | `mam-points.timer` daily 05:43 Europe/Zurich (low-power hours, outside the DST hour and the nightly jobs), catch-up if missed |
| Metrics | `/var/lib/node-exporter/textfile/mam_points.prom`: `mam_points_estimated` (at the last write), `mam_points_rate_per_hour`, `mam_points_last_update_timestamp_seconds`. Estimate in Grafana: `last + rate × (time() - ts)/3600`, needs the raw balance, which is only in the state file |
| Install | `sudo install -d -o pi -g pi /var/lib/mam-points && ln -sf $PWD/mam-points.py ~/.local/bin/mam-points && sudo install -m 0644 ../systemd/mam-points.{service,timer} /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now mam-points.timer` |
| By hand | `systemctl start mam-points.service` then `journalctl -u mam-points -n 5` |
| Test | `python3 scripts/test_mam_points.py` |

## repo-drift
`repo_drift.py` lists what was changed live but not in the repo (or the reverse). Same file on fastpi and beefy (beefy repo: `Docker/_global/scripts/`): keep them identical. Never fixes anything.

| Kind | Compared | Repo side (existing mapping, nothing new) |
|---|---|---|
| `compose` | each running container vs `docker compose config` of the project it was started from: image, env **keys**, mount targets, labels, plus the container's `config-hash` vs `config --hash` (repo compose edited, container not recreated) | the compose files named in the container's own labels |
| `unit` | regular files and drop-ins in `/etc/systemd/system` and `~/.config/systemd/user` (snapd and generated units skipped) | the file with the same name in the repo, or the `install` lines of the repo's install scripts |
| `script` | `/usr/local/sbin`, `/usr/local/bin`, `/usr/local/libexec/fastpi`, `/usr/local/lib/*` (binaries skipped) | `install` lines (`$HERE/x /usr/local/sbin/y`), the `SCRIPTS=( )` list of `install-root-scripts.sh`, else the same name (`_` = `-`, no `.sh`/`.py`) |
| `etc` | `/etc` drop-ins (sysctl.d, modprobe.d, tmpfiles.d, sshd_config.d, apt.conf.d, docker, `*.conf.d` of systemd) not owned by a package; sysctl files vs `/proc/sys`; keys of `*.conf.d` vs `systemd-analyze cat-config` (a later file wins) | same name in the repo, else the path must appear in a repo doc or script |
| `worktree` | `git status` of the repo: modified, deleted, untracked | - |

| | |
|---|---|
| Output | fastpi: `/var/lib/node-exporter/textfile/repo_drift.prom` (`drift_items{host,kind}`, `drift_collect_errors{host,kind}`, `drift_last_run_timestamp_seconds{host}`) and `~/.local/state/repo-drift/drift.json` (the item list, read by `arch_page.py`: section "Drift (repo vs live)"). beefy: the same under `~/.local/state/repo-drift/`, copied by `beefy-idle-pull` to `repo_drift_beefy.prom` (kept while beefy sleeps) |
| No HELP/TYPE | both hosts pass `--no-help`: fastpi's and beefy's files carry the same families and node-exporter fails the whole scrape when only one has HELP/TYPE |
| Never in the output | env values (keys only), file contents |
| A kind that cannot be collected | `drift_collect_errors=1`, its items stay the previous night's |
| When | fastpi `repo-drift.timer` 04:28 Europe/Zurich; beefy 04:19 (inside its window, `Server/9-Night-Schedule.md`) |
| Alerts | `RepoDriftPersists` (> 0 for 24 h, per host and kind), `RepoDriftCheckStale`, `RepoDriftCollectFailing`: `Docker/grafana/prometheus/rules/drift.yml`, test `tests/drift_test.yml` |
| Install | `mkdir -p ~/.local/state/repo-drift && sudo install -m 0644 ../systemd/repo-drift.{service,timer} /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now repo-drift.timer` |
| By hand | `systemctl start repo-drift.service`, or `python3 scripts/repo_drift.py --host fastpi --prom /dev/null --json /dev/null` (prints every item) |
| Test | `python3 scripts/test_repo_drift.py`, unit sandbox: `scripts/test_unit_sandbox.sh` |

## arch-page
One generated notes page with the real homelab, so nobody re-reads compose files and `docker inspect`. Lives here (not in `Docker/Notes/`) because it describes the whole host and its unit sits next to the other host timers in `../systemd/`.

| | |
|---|---|
| Output | `~/notes/docs/homelab-architecture.md` (written atomically; the notes build picks it up), linked from the notes index and nav |
| Sources | fastpi: `docker inspect`, `Traefik/traefik/dynamic/*.yml` (hostnames, SSO = `authentik@file` middleware or OIDC/OAUTH env **names**), `auto-update.conf`, `Server/5-Backup/backup.sh --list` (paths vs. each container's rw mounts). beefy: one `ssh beefy-direct` call (inspect, its `auto-update.conf`, `beefy-backup.sh --list`), never wakes it; asleep = cached section "as of <time>" in `~/.cache/arch-page/beefy.json` (parsed rows only, no env). tower: never contacted, Waker `/status` + the stack scripts in `~/backups/tower-flash/latest` |
| Never on the page | env values, tokens, labels; a test checks this |
| Drift section | the item lists of `repo_drift.py` for fastpi (`~/.local/state/repo-drift/drift.json`) and beefy (same file over the one ssh call; cached with beefy's data while it sleeps), see "repo-drift" |
| Flags | `!ip` unpinned network IP, `!hc` running without healthcheck: facts, not a policy |
| When | `arch-page.timer` 04:35 Europe/Zurich (inside beefy's night window) and 10 min after boot, catch-up if missed |
| Install | `sudo install -m 0644 ../systemd/arch-page.{service,timer} /etc/systemd/system/ && mkdir -p -m 0700 ~/.cache/arch-page && sudo systemctl daemon-reload && sudo systemctl enable --now arch-page.timer` |
| By hand | `systemctl start arch-page.service`, or `python3 scripts/arch_page.py --print` |
| Test | `python3 scripts/test_arch_page.py`, unit sandbox: `scripts/test_unit_sandbox.sh` |
