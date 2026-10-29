# _global/scripts

| Script | What |
|---|---|
| `docker-user-lan-guard.sh [--persist]` | DOCKER-USER: which containers may reach the LAN (FORWARD) |
| `host-input-guard.sh [--persist]` | HOST-GUARD/HOST-GUARD6: which containers / VPN peers may reach the host itself (INPUT) |
| `host-output-guard.sh [--persist]` | HOST-OUT-GUARD: what the host itself (incl. host-network containers) may open on beefy (OUTPUT) |
| `iptables-persist.sh` | writes `/etc/iptables/rules.v4/v6` with only those chains; never `netfilter-persistent save` |
| `smoke-test.sh` | end-to-end checks, must stay green |
| `update-project.sh`, `auto_update.py` | image updates (`UPDATE-RUNBOOK.md`, rollback restores compose/.env + old image). Test: `./test_update_project.sh`, `python3 test_auto_update.py` |
| `oob-alert.sh` | Telegram alert that bypasses the edge; `--check` proves the path without sending (batch start), `--test` sends a 🧪 message (to `TEST_CHAT_ID` in `oob-alert.env` if set, else the alert chat). Test: `./test_oob_alert.sh` |
| `maintenance-silence.sh on [hours] [reason] \| off \| status` | Alertmanager silence for batch/upgrade work (crash loops, container down/unhealthy, file changes, reboots, own SSH logins), default 4 h, max 24 h; only touches its own silences. Test: `./test_maintenance_silence.sh` |
| `subscription-alerts.py` | Telegram warnings for subscription deadlines, see below |
| `mam-points.py` | MyAnonamouse bonus-points estimator + Telegram warnings, see below |

## host-input-guard
- New host port needed by a container or the VPN: add it to the port lists in the script, `sudo ./host-input-guard.sh --persist`.
- Something from a container to the host times out: `sudo journalctl -k | grep 'host-guard drop'`.
- Remove the OUTPUT guard: `sudo iptables -D OUTPUT -d 192.168.1.102/32 -j HOST-OUT-GUARD`, then `sudo ./iptables-persist.sh`. Something on the host can't reach beefy: `sudo journalctl -k | grep 'host-out-guard drop'` (shows UID).
- Remove (one command): `for i in docker0 br-+; do sudo iptables -D INPUT -i $i -j HOST-GUARD; done; for i in docker0 br-+ eth0; do sudo ip6tables -D INPUT -i $i -j HOST-GUARD6; done`, then `sudo ./iptables-persist.sh`.

## image-cleanup
| | |
|---|---|
| What | `image-cleanup.sh`: removes images no container (running or stopped) uses, and build cache, both after 14 days. Never volumes, networks or containers. |
| When | weekly `image-cleanup.timer`: fastpi Sun 05:30, beefy Sun 04:20 (inside the maintenance wake, never a wake of its own). Install: `_global/install-image-cleanup.sh` |
| Unused clock | own state `/var/lib/image-cleanup/first-seen` (image ID, first seen unused). `prune --filter until` dates by build time, which would delete an image the day it was superseded |
| Rollback | `update-project.sh` tags the previous image `<repo>:rollback-<date>-<project>`, so a superseded image stays 14 days. `:rollback-*` tags: kept 14 days from the date in the tag (else the tag time), then cleaned. Kept always: images of any container, other tags containing `rollback`, images referenced in the repo's compose files and scripts. First run: dangling images and older tags of a repo in use start their 14 days then |
| Metrics | `docker_image_cleanup_{freed_bytes,removed_images,rollback_window_images,failed_images,last_run_timestamp_seconds}` in `image_cleanup.prom` |
| By hand | `scripts/image-cleanup.sh --dry-run` lists what would go; `systemctl start image-cleanup.service` runs it (`KEEP_DAYS=7` env to change the age) |
| Test | `scripts/test_image_cleanup.sh` (fake docker) |

## subscription-alerts
| | |
|---|---|
| What | `subscription-alerts.py`: reads the `[[subscriptions]]` of Seerr's `indexer-bar/limits.toml` (beefy), sends Telegram via `oob-alert.sh`. `lifetime = true` never alerts |
| Stages | 🟡 ≤ 30 days left, 🟠 ≤ 7 days, 🔴 on the end date, 🔴 the day after ("expired yesterday"). Same colours as the Seerr bar. Services on the same end date and stage share one message |
| Once | each stage once per (service, end date) in `/var/lib/subscription-alerts/state.json`. Renewal = change `expires`: the new date starts fresh, the old date's warnings are dropped. First run late (e.g. 23 days left) sends only the current stage. A failed send is retried at the next run |
| When | `subscription-alerts.timer` daily 05:37 Europe/Zurich (low-power hours, outside the DST hour and the nightly jobs), 5 min after boot, catch-up if missed. fastpi only, beefy is never woken |
| List cache | `/var/lib/subscription-alerts/limits.toml` (also read by ABR's requests bar for `seerr = true` entries, `Audiobook-Requests/README.md`): every run tries `ssh beefy-direct cat …/limits.toml` (5 s timeout); valid copy replaces the cache, otherwise the old one stays. Older than 7 days: logged and said in the message details |
| Install | `sudo install -m 0644 ../systemd/subscription-alerts.{service,timer} /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now subscription-alerts.timer` |
| By hand | `systemctl start subscription-alerts.service` then `journalctl -u subscription-alerts -n 5`; `scripts/subscription-alerts.py --test` sends one 🧪 test message |
| Renew | change `expires` in `Seerr/indexer-bar/limits.toml` on beefy and commit (next beefy-reachable run picks it up; to force: the command above) |
| Test | `python3 scripts/test_subscription_alerts.py` |

## mam-points
| | |
|---|---|
| What | `mam-points.py` (CLI `mam-points` → `~/.local/bin`): estimates the MyAnonamouse bonus points from the last known balance + rate. **No call to MAM** (its rules forbid automating unlisted endpoints) |
| Estimate | `min(99999, points + rate × hours since update)` |
| Commands | `mam-points status` · `set 51655 [--rate 309.9]` (current balance) · `spent 25000` · `reset` (= set 0) · `rate 309.9` (new points/hour) · `check [--preview]` (timer; `--preview` sends one sample 🟡 with made-up points) |
| Epoch | `set`, `spent`, `reset`, `rate` each start a new epoch; each alert once per epoch |
| Alerts | 🟡 estimate ≥ 90,000 (days until the cap), 🔴 ≥ 99,999 (points wasted). Both crossed in one night: only 🔴. The message names the exact crossing time, so one check per night is enough |
| Input | balance 0–99,999, spent > 0 and ≤ estimate, rate > 0; `51,655` accepted |
| State | `/var/lib/mam-points/state.json` (owned by `pi`, created by the unit's `StateDirectory`) |
| When | `mam-points.timer` daily 05:43 Europe/Zurich (low-power hours, outside the DST hour and the nightly jobs), catch-up if missed |
| Metrics | `/var/lib/node-exporter/textfile/mam_points.prom`: `mam_points_estimated` (at the last write), `mam_points_rate_per_hour`, `mam_points_last_update_timestamp_seconds`. Estimate in Grafana: `last + rate × (time() - ts)/3600`, needs the raw balance, which is only in the state file |
| Install | `sudo install -d -o pi -g pi /var/lib/mam-points && ln -sf $PWD/mam-points.py ~/.local/bin/mam-points && sudo install -m 0644 ../systemd/mam-points.{service,timer} /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now mam-points.timer` |
| By hand | `systemctl start mam-points.service` then `journalctl -u mam-points -n 5` |
| Test | `python3 scripts/test_mam_points.py` |
