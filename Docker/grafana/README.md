# Grafana

Monitoring stack: Grafana, Prometheus, Alertmanager, InfluxDB, Telegraf, exporters. Grafana: https://grafana.holy-grail.ch (Holy Grail: group `homelab-admins` = GrafanaAdmin, `homelab-users` = Viewer).

## Dashboards

Provisioned from `provisioning/dashboards/*.json` into folder `Homelab`; edits to a file load within 30 s.

| Dashboard | uid | Shows |
|---|---|---|
| CrowdSec | `crowdsec-overview` | bans, attacks, bouncer and hub health (`Docker/CrowdSec/README.md`) |
| Updates & security | `updates-security` | OS/image updates, CVEs, ClamAV, rootkit/Lynis, CrowdSec versions, firing security alerts (`Server/4-Security-Monitoring/README.md`) |
| fastpi — RAM, containers & electricity | `fastpi-resources` | per-container RAM, plug power (InfluxDB), Authentik workers row |
| fastpi — system (CPU, RAM, disk) | `rYdddlPWk` | node-exporter full view (Prometheus) |
| fastpi — Pi hardware (temperature, throttling) | `sF7d-FHZz` | Pi telemetry (InfluxDB) |
| LanguageTool — usage watch | `languagetool-watch` | LanguageTool usage |
| Homelab — morning view | `homelab-morning` | one phone-sized look: storage, downloads, requests, popular job, backups, security, certs, domains, subscriptions, SMART, indexers (see Homelab — morning view) |
| Usage per user | `usage-per-user` | Seerr requests, Jellyfin plays, Audiobookshelf listening per user (see Usage per user) |

## Container and reboot alerts

`container-exporter/container_exporter.py`, every minute (`container-exporter.timer`, root), writes `container_status.prom` for node-exporter (`docker compose run` one-offs, label `com.docker.compose.oneoff=True`, are left out). Rules: `prometheus/rules/containers.yml`, `prometheus/rules/host.yml`.

| Alert | Fires when | Severity |
|---|---|---|
| `ContainerDown` | restart policy always/unless-stopped, not stopped by hand, not running for 5 min | warning |
| `ContainerCrashLooping` | 3+ restarts in 15 min | warning |
| `ContainerUnhealthy` | healthcheck unhealthy for 10 min | warning |
| `ContainerExporterStale` | no export for 10 min | info |
| `HostRebootedUnclean` | boot < 6 h ago, journald found a dirty journal (power loss, hard reset) | warning |
| `HostRebooted` | boot < 6 h ago, clean shutdown | info |
| `MonitoringDown` (sent by the exporter itself, Telegram) | Prometheus or Alertmanager not answering for 10 min; once, and once when back | - |

Not covered: fastpi off or offline. That needs an external dead-man's switch; `AlertingHeartbeat` is only a monthly email.

```bash
../_global/install-root-scripts.sh   # root runs a root-owned copy in /usr/local/libexec/fastpi; re-run after editing the script
sudo cp container-exporter/systemd/container-exporter.* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now container-exporter.timer
python3 container-exporter/test_container_exporter.py
docker run --rm --network none --entrypoint sh -v "$PWD/prometheus":/w:ro -w /w/tests prom/prometheus:v3.16.0 -c 'promtool test rules *.yml'   # glob expands inside the container
docker kill -s HUP prometheus   # reload rules
```

## Host resource alerts

`prometheus/rules/host-resources.yml` (node-exporter, job `raspberry-pi`; disks ext4/xfs/btrfs/vfat). Warning and critical use disjoint ranges.

| Alert | Fires when | Severity |
|---|---|---|
| `HostFilesystemSpaceLow` / `…Critical` | < 15% free for 30 min / < 5% for 5 min | warning / critical |
| `HostTmpFull` | `/tmp` (RAM-backed tmpfs) over 80% used for 5 min | warning |
| `HostFilesystemFillingUp` | < 40% free and the 6 h trend hits 0 within 24 h, for 1 h | warning |
| `HostFilesystemReadOnly` | a disk is mounted read-only for 2 min | critical |
| `HostInodesLow` / `…Critical` | < 10% inodes free for 30 min / < 5% for 5 min | warning / critical |
| `HostMemoryLow` / `…Critical` | MemAvailable < 10% for 10 min / < 5% for 5 min | warning / critical |
| `HostSwapHigh` | > 80% of swap used for 15 min | warning |
| `HostCpuHot` / `HostCpuThrottling` | CPU > 75 °C for 10 min / > 80 °C for 5 min | warning / critical |
| `HostNvmeHot` | NVMe at or over its own warning temperature for 10 min | warning |
| `HostLoadHigh` | load15 > 2 per core for 30 min | warning |
| `HostOomKill` | kernel OOM kill in the last 15 min | warning |
| `CustomizationCheckFailing`, `PortUpdaterReattachLoop`, `CustomizationCheckStale` | customization check failed two runs in a row (names the id), `port_updater` reattached >= 2 in 6 h, checker stale > 8 h (`rules/customization-checks.yml`, `_global/scripts/README.md` "customization-check") | warning |
| `ClaudeRemoteRestartBlocked` | the 04:00 claude-remote restart deferred > 1 day; names the reason and first blocking command (`rules/claude-remote.yml`, `Server/8-Claude-Scratch/`) | warning |

## Authentik metrics

Job `authentik` scrapes `authentik-server:9300` over the `authentik_authentik_internal` network (Prometheus joins it; the port is not published). Forward-auth latency = `authentik_main_request_duration_seconds{dest="embedded_outpost"}` (summary quantiles, Traefik calls the outpost directly so it is not in Traefik metrics); `dest="core"` is the Django side. Dashboard `fastpi-resources`, row "Authentik workers" (RAM, SSO latency from Traefik, forward-auth latency); baseline `~/reports/2026-11-10/authentik-workers-baseline.md`.

## Activity metrics

Job `activity` scrapes `activity:8080/metrics` every 30 s over the internal `activity_metrics` network (10.24.40.0/29, defined by `../Activity`; Prometheus joins it). Anonymous counts only: `activity_streams{kind,quality,mode}`, `activity_watching_streams`, `activity_downloads{state,kind,quality}`, `activity_listening_sessions`, `activity_audiobook_downloads{state}`, `activity_beefy_up`, `activity_beefy_snapshot_age_seconds`, `activity_viewer_active`, `activity_last_poll_timestamp_seconds`: last-known values, refreshed only while someone views the page (`../Activity/README.md`).

## Prometheus self-monitoring

Job `prometheus` scrapes `localhost:9090`. Rules: `prometheus/rules/prometheus-self.yml`, all warning.

| Alert | Fires when |
|---|---|
| `PrometheusConfigReloadFailed` | last reload failed for 10 min (old config still active) |
| `PrometheusRuleFailures` / `PrometheusMissingRuleEvaluations` | a rule group errors / skips evaluations for 15 min |
| `PrometheusErrorSendingAlerts` / `PrometheusNotificationsDropped` | > 1% send errors / any drop to Alertmanager for 15 min |
| `PrometheusNotConnectedToAlertmanagers` | no Alertmanager discovered for 10 min |
| `PrometheusTSDBCompactionsFailing` / `…ReloadsFailing` | failures in the last 3 h, for 4 h |
| `PrometheusTSDBWALCorruptions` | WAL corruption in the last 3 h |
| `PrometheusNotIngestingSamples` | no samples appended for 10 min |
| `TargetDown` | `up == 0` for 5 min; excludes `blackbox-*` (`BlackboxExporterDown`; sleeping beefy/tower stay `up`), `alertmanager` (`AlertmanagerDown`), `cup` (`CupNotReporting`) |
| `ContainerImageUpdatesAvailable` | `last_over_time(cup_updates_available[20m]) > 0` for 30 min; `notify: weekly`, no message of its own (Monday digest) |
| `CupNotReporting` | `last_over_time(up{job="cup"}[20m]) == 0` for 1 h; Cup is scraped every 15m but a sample is only current for 5m, so a bare selector would never hold for `for:` |

`prometheus.yml`, `blackbox.yml` and `alertmanager.yml` are single-file bind mounts: an editor that replaces the file leaves the container on the old inode, so after editing them run `docker compose up -d --force-recreate <service>` instead of a HUP/reload.

## Endpoint probes

blackbox jobs in `prometheus/prometheus.yml`, rules in `prometheus/rules/public-endpoints.yml`. `blackbox-exporter` resolves `*.holy-grail.ch` through AdGuard to Traefik on the LAN (from a container IP, so outside `local-networks@file`).

| Job | Pass | Targets | Alert |
|---|---|---|---|
| `blackbox-public` | 200/301/302/401/403 | audiobookshelf, sso | `PublicEndpointDown`, `AllPublicEndpointsDown` |
| `blackbox-gated` | 302 to sso.holy-grail.ch | cup, claude-mockups, tracker, avatars, activity (WAN: after its tunnel hostname, `../Activity/README.md`) | `PublicEndpointDown` |
| `blackbox-gated-wake` (15m) | 302 to sso.holy-grail.ch | requests (Seerr, behind `requests-wake`) | `WakeGatedEndpointNotGated` |
| `blackbox-lan-locked` | 403 | radarr, sonarr, prowlarr, bazarr, qbittorrent, sabnzbd, stonks, traefik, adguard | `LanLockedEndpointNotLocked` |
| `blackbox-wan-public` | 200/301/302/401 | audiobookshelf, sso | `PublicPathDown`, `CloudflareTunnelDown` |
| `blackbox-wan-gated` | 302 to sso.holy-grail.ch | cup, claude-mockups, tracker, avatars | `PublicPathDown`, `CloudflareTunnelDown` |
| `blackbox-wan-lan-locked` | 403 with Traefik's body `Forbidden` | stonks | `PublicPathDown`, `CloudflareTunnelDown` |

`blackbox-wan-*` run on `blackbox-exporter-wan` (uid 65010, read-only), which resolves through 1.1.1.1/9.9.9.9 and so goes through Cloudflare and the tunnel. Only hostnames with a public DNS record (radarr & co. have none). `CloudflareTunnelDown` = every Cloudflare probe fails while a LAN probe passes; it also fires when fastpi's internet is down.

| Alert | Fires when |
|---|---|
| `CloudflaredTunnelDown` | `cloudflared_tunnel_ha_connections < 1` for 5 min (job `cloudflared`, `cloudflared:20241` over the external network `infra__cloudflare_default`, not published on the host); inhibits `CloudflareTunnelDown` and `PublicPathDown`; a dead scrape is `TargetDown` |

## beefy power

`prometheus/rules/beefy-power.yml`, tests `prometheus/tests/beefy-power_test.yml` + `beefy-power-dst_test.yml`. Probe: `blackbox-beefy` (ssh, never wakes it).

| Alert | Fires when |
|---|---|
| `BeefyWakeLoop` | > 60 up/down changes in 24 h (planned wakes give 7-41), holds 6 h after it drops below; one message per episode |
| `BeefyAwakeLong` | up 6 h since beefy's own boot time (`beefy_boot_time_seconds`, so a Prometheus restart cannot fire it early) with fresh idle metrics (< 15 min) (warning). Not new between 03:58 and 04:45 local; one already firing carries on. Telegram only (`telegram-beefy-awake`, tg.beefyawake): one message per episode, no repeat, no resolved message; "awake since" is the boot time; hours awake per day are in the daily digest. Says what keeps it awake from `beefy_idle_busy{reason}` / `beefy_idle_info{detail}`: the idle watcher on beefy writes them, `Server/4-Security-Monitoring/beefy-idle-pull.timer` copies them every 5 min to `beefy_idle.prom` (removed while beefy is down) |

## Jellyfin Popular movies and shows

`prometheus/rules/jellyfin-popular.yml`, test `prometheus/tests/jellyfin-popular_test.yml`. Source: beefy `Docker/Jellyfin/scripts/popular.py` → `jellyfin-popular.prom` (copied by `beefy-idle-pull`).

| Alert | When |
|---|---|
| `JellyfinPopularFailed` | `jf_popular_last_run_success == 0` for 10 min (run failed or too many title lookups failed; lists of the last good run stay), warning |
| `JellyfinPopularStale` | no run for more than 2 days, for 1 h (after 9 days the request backend refuses everything), warning |

## Jellyfin playback watch

`prometheus/rules/jellyfin-playback.yml`, test `prometheus/tests/jellyfin-playback_test.yml`. Source: the beefy `playback-watch` service → `~/.local/state/jellyfin-playback/playback.prom` → `beefy_playback.prom` (copied by `beefy-idle-pull`, kept while beefy sleeps).

| Alert | When |
|---|---|
| `JellyfinPlaybackStutter` | last incident (`jellyfin_playback_last_incident_timestamp_seconds`) less than 15 min ago, one alert for all kinds/clients, ends 15 min after the last incident; warning, normal Telegram route; lists recent incidents per kind and client, the active auto-fixes and `ssh beefy playback-watch report --since 1h` |
| `JellyfinPlaybackWatchDown` | no poll for 15 min while beefy is awake (fresh idle metrics), for 10 min, info, `notify: digest` |

## Activity page

No alert rules (removed 2026-11-12): the service polls only while the page is viewed, so its data is stale by design when nobody looks, and a viewer sees the failure on the page. The service down is `TargetDown`.

## Authentik service tokens

`prometheus/rules/authentik-tokens.yml`, test `prometheus/tests/authentik-tokens_test.yml`. Source: `Avatar-Picker/scripts/rotate-secrets.sh token-auto` (timer `avatar-token-rotate`, Tue 22:47) writes `authentik_tokens.prom`; it rotates the token 45 days before expiry.

| Alert | When |
|---|---|
| `AuthentikTokenExpiringSoon` | token expires in < 30 days, for 1 h (rotation did not run or failed), warning |
| `AuthentikTokenRotationFailed` | `authentik_token_rotation_success == 0` for 10 min (old token put back), warning |
| `AuthentikTokenCheckStale` | no check for more than 9 days, for 1 h, warning |

## beefy storage and mover

`prometheus/rules/beefy-storage.yml`, test `prometheus/tests/beefy-storage_test.yml`. beefy writes `storage.prom` (every minute while awake) and `mover.prom` (end of each nightly SSD->HDD mover run); `Server/4-Security-Monitoring/beefy-idle-pull.sh` copies them to `beefy_storage.prom` / `beefy_mover.prom` (kept while beefy sleeps, an invalid fetch keeps the old copy). The mover counters are only written on runs with the SSD tier >= 70 % (absent otherwise); `beefy_disk_smart_raw` comes from `smartctl -n standby`, so series have gaps. `ssd` = both SSDs combined. The daily digest shows SSD/HDD used %, SSD TB written, HDD start/stops and power cycles of the last 24 h and, after a run that moved something, titles, GB and SSD before -> after.

| Alert | Fires when | Severity |
|---|---|---|
| `BeefySsdFilling` | SSD used >= 80 % for 10 min (the mover keeps it <= 70 %; at 80 % mergerfs sends new downloads to the HDD) | warning |
| `BeefyHddFilling` | HDD used 80-90 % for 10 min | warning |
| `BeefyHddFull` | HDD used >= 90 % for 10 min (Radarr/Sonarr refuse imports); replaces `BeefyHddFilling` (exclusive expressions) | critical |
| `BeefyMoverFailed` | last run `success == 0` and not a dry run, for 10 min; names the failed titles, points at `journalctl -u beefy-mover` | warning |
| `BeefyMoverNotRun` | last mover run older than 50 h, for 1 h | warning |
| `BeefyMoverVerifyFailures` | `beefy_mover_verify_failures > 0` (a copy read back differed and was discarded), 10 min | warning |
| `BeefyMoverHddOverflow` | `beefy_mover_hdd_overflow_files > 0` (downloads spilled onto the HDD, both SSDs at their mergerfs limit) | warning |
| `BeefyMoverNothingToMove` | real run, SSD used after >= 75 % and 0 titles moved | warning |
| `BeefyHddSpinningUpTooOften` | HDD `Start_Stop_Count` rose by > 30 in 24 h (max - min, tolerates gaps) | warning |
| `BeefyMoverStagingOrphans` / `BeefyMoverDuplicates` | leftovers in `hdd-cold/.tier-staging` / videos on an SSD and the HDD at one path; `notify: digest` | info |
| `BeefySsdWearHigh` | SSD `Wear_Leveling_Count` raw (P/E cycles, QVO rated ~1000) >= 800; `notify: digest` | info |
| `BeefyStorageStale` | `beefy_storage.prom` older than 3 days or missing, for 1 h; `notify: digest` | info |

## Media language (beefy)

`prometheus/rules/media-language.yml`, test `prometheus/tests/media-language_test.yml`. Source: beefy `Movie-Downloads/scripts/language-missing.py` → `security_scan.py media` (04:20 pull) → `media_language_beefy.prom`.

| Alert | Fires when | Severity |
|---|---|---|
| `AudioLanguageNotFound` | a Radarr/Sonarr title tagged `audio-swiss-german` waits 7 days for a Swiss German release (or a grab of it failed later); holds 5 days; `notify: digest`, listed in the daily digest | info |

The textfile stays on fastpi while beefy sleeps, so the series do not go stale; details in `HomeLab-BeefyServer` `Docker/Movie-Downloads/README.md`, "Swiss German not found alert".

## Expiry and disk health

Rules `prometheus/rules/expiry.yml`, `prometheus/rules/disk-health.yml`, tests `prometheus/tests/expiry_test.yml`, `disk-health_test.yml`. The daily digest gets a section **⏰ Expiry and disks** only when something is due: certs ≤ 21 d, domains ≤ 30 d, subscriptions ≤ 30 d (No-IP hostnames ≤ 5 d: their 30-day confirm window would always be listed), firing `Smart*` alerts.

| Job | Runs | Writes | Source |
|---|---|---|---|
| `status-exporter-daily.timer` (pi) | 05:50 Europe/Zurich, `Persistent` | `status_certs.prom`, `status_domains.prom` | TLS handshake with Traefik `127.0.0.1:443` (SNI) for every hostname routed with a `certResolver` in `Traefik/traefik/dynamic`; RDAP for `status-exporter/domains.toml`; DDNS names resolved and compared with the WAN address (`1.1.1.1/cdn-cgi/trace`) |
| `status-exporter.timer` (pi) | every 5 min, file reads only | `status_subscriptions.prom`, `status_indexers_fastpi.prom` | `/var/lib/subscription-alerts/limits.toml` + `[mam] vip_expires` of `Audiobook-Requests/abr-bar/limits.toml`; `/var/lib/abr-bar/usage.json` |
| `smart-exporter.timer` (root) | every 30 min | `smart_fastpi.prom` | `smartctl -n standby -j -a` per disk: a parked disk is skipped, never woken; its last values stay (`smart_standby 1`). Disks named by mountpoint (`/` = `system`) |
| beefy `smart-exporter.timer` / `media-metrics.timer` | 30 / 5 min while awake | `smart_beefy.prom`, `beefy_media.prom` | verbatim copy of `smart_exporter.py`; `Movie-Downloads/scripts/media-metrics.py`; pulled by `beefy-idle-pull.sh`, kept while beefy sleeps |
| beefy idle watcher (`beefy_idle_watcher.py`) | every cycle while awake | `beefy_idle.prom` | adds `beefy_idle_cpu_temp_celsius` (coretemp package) and `beefy_idle_pch_temp_celsius` for the fastpi-resources Temperatures panel; file removed while beefy sleeps, so the series just end (no alert) |

fastpi's two USB disks (`seagate-black` Expansion `0bc2:231a`, `seagate-red` One Touch `0bc2:ab53`) give no SMART: the kernel's `uas` driver blocks ATA pass-through for every Seagate enclosure (`US_FL_NO_ATA_1X`, `uas-detect.h`), so every `-d` type fails and `-n standby` reads them as asleep (2026-11-01). They show `smart_standby 1` and are listed below, so `SmartDiskUnchecked` stays silent for them. Possible fix (owner decision, needs a reboot, the kernel calls these bridges' pass-through broken): append `usb-storage.quirks=0bc2:231a:,0bc2:ab53:` to `/boot/firmware/cmdline.txt`; check after the reboot: `sudo smartctl -d sat -H /dev/sda`.

**No SMART possible** (`homelab:smart_impossible` in `prometheus/rules/disk-health.yml`, keep both in sync; `SmartDiskUnchecked` ignores these, a new or unlisted disk still alerts):

| Host | Disk | Reason |
|---|---|---|
| fastpi | `seagate-black` | Seagate Expansion USB (`0bc2:231a`): `uas` blocks ATA pass-through (every `smartctl -d` type tried 2026-11-02, `-d scsi` gives no values); a `usb-storage` quirk + reboot would fix it: **not done, owner decision 2026-11-02** |
| fastpi | `seagate-red` | Seagate One Touch USB (`0bc2:ab53`): same |

- A TLS handshake runs no Traefik middleware: wake-gated routes (Jellyfin, Seerr, Nextcloud) are checked without waking beefy/tower. Traefik's own `traefik_tls_certs_not_after` lists every cert in the ACME store, including ones no router uses any more; the alerts use only the served certs.
- `.ch` RDAP (rdap.nic.ch) has no end date: `source="anniversary"` = next registration anniversary. holy-grail.ch has its paid end date in `domains.toml` (`expires`, `source="manual"`; GoDaddy, renewed yearly; Cloudflare only does the DNS): a set date warns through `subscription-alerts.py` (Telegram) and shows with the subscriptions, `DomainExpiringSoon` covers only domains without one. After each renewal update `expires`.
- No-IP free hostnames (`lang-tool.ddns.net`, `wg-aemtli.ddns.net`) need a confirm every 30 days (mail ~7 days before; unconfirmed = deleted). `confirmed = <date>` per `[ddns."…"]` in `domains.toml` gives the end date (+30 days): Telegram via `subscription-alerts.py` at 5, 3 and 1 days left, on the deadline day (05:37 run, No-IP deletes the hostname that day) and the day after ("deadline passed: re-create the hostname"), dashboard/digest show it as `kind="No-IP hostname"`. After confirming set the new date (or tell Claude "No-IP confirmed"). `DdnsHostnameNotResolving` stays as backstop.
- Subscriptions: no rule, `subscription-alerts.py` sends the Telegram warnings; the dashboard and digest show days left.

| Alert | Fires when | Severity |
|---|---|---|
| `TlsCertExpiringSoon` / `TlsCertExpiryCritical` | served cert ends in 7-21 d / ≤ 7 d, for 1 h | warning / critical |
| `TlsCertNotValid` | served cert does not verify (wrong name, Traefik default cert) | warning |
| `TlsCertProbeFailed` | no handshake for a routed hostname; `notify: digest` | info |
| `DomainExpiringSoon` | registration end (or anniversary) ≤ 30 d | warning |
| `DomainStatusProblem` | RDAP status inactive / hold / redemption / pending delete | warning |
| `DdnsHostnameNotResolving` / `DdnsHostnameWrongAddress` | DDNS name has no address / not the WAN address (`notify: digest`) | warning / info |
| `StatusExporterStale` | certs or domains not run for 2 days, or an RDAP lookup failed; `notify: digest` | info |
| `SmartDiskFailing` / `SmartNvmeCriticalWarning` | SMART overall health FAILED / NVMe critical warning bits | critical |
| `SmartPendingSectors` | pending sectors > 0 | warning |
| `SmartErrorsGrowing` | reallocated, offline-uncorrectable or media errors above their 24 h minimum | warning |
| `SmartWearHigh` | wear indicator ≥ 80 % (NVMe percentage used, SSD normalized wear) | warning |
| `SmartTemperatureHigh` | freshly read (< 1 h) and HDD ≥ 55, SATA SSD ≥ 65, NVMe ≥ 75 °C for 30 min (fastpi NVMe: `HostNvmeHot`) | warning |
| `SmartExporterStale` | fastpi not run for 2 h, beefy for 3 days, or a disk unreadable; `notify: digest` | info |
| `SmartDiskUnchecked` | a parked disk (standby at every run, never woken) with no SMART reading for 14 days: last read older than 14 days, or never read and parked 14 days (`for: 14d`); not for disks under "No SMART possible"; `notify: digest` | warning |

```bash
../_global/install-root-scripts.sh   # smart_exporter.py runs as root from /usr/local/libexec/fastpi
sudo install -m 0644 status-exporter/systemd/status-exporter*.{service,timer} smart-exporter/systemd/smart-exporter.{service,timer} /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now status-exporter.timer status-exporter-daily.timer smart-exporter.timer
python3 status-exporter/test_status_exporter.py && python3 smart-exporter/test_smart_exporter.py
sudo systemctl start status-exporter-daily.service && cat /var/lib/node-exporter/textfile/status_domains.prom
```

## Homelab — morning view

Dashboard `homelab-morning` (`provisioning/dashboards/homelab-morning.json`), rows of stat tiles and small tables that stack to one column on a phone.

| Row | Metrics |
|---|---|
| At a glance | `ALERTS` (critical + warning), `backup_last_success_timestamp_seconds`, `clamav_infected_last_run`, `security_repo_leaks_total` |
| Storage | `beefy_storage_*`, `beefy_mover_*`, `beefy_disk_smart_raw` (HDD start/stop, power cycles per 24 h) |
| beefy wake | `beefy_wake_phase{phase}` (state timeline), `beefy_wake_power_cycles_total`, `beefy_wake_failures_total{reason}` (Beefy-Waker textfile `beefy_wake.prom`); dashboard annotations "power-cycle" and "wake failed" on their `changes(…[2m]) > 0` |
| Downloads and requests | `beefy_downloads_night_pending`, `beefy_downloads_queue{state}`, `beefy_downloads_night_imported{,_bytes}{app}` (last 22:00-06:00 window), `beefy_requests{state}` (Seerr `/request/count`), `beefy_request_badges{state}` (request-state.json) |
| Jellyfin popular | `jf_popular_last_run_timestamp_seconds`, `jf_popular_last_run_success` (0/1), `jf_popular_errors`, `jf_popular_items{list}`: written by the beefy popular job to `/home/buntu/.local/state/jellyfin-popular.prom` (the pull copies it only when it has a `jf_popular_last_run_timestamp_seconds ` line) |
| Jellyfin playback | `jellyfin_playback_incidents_total{kind}` (increase per 15 min), `jellyfin_playback_stall_seconds_total{client}`, `jellyfin_playback_active{method}`, `jellyfin_playback_autofix_active{action}` (state timeline) |
| Backups and security | `backup_last_status`, `backup_last_bytes_added`, `security_image_vulnerabilities_fixable` |
| Certificates, domains, subscriptions | `tls_cert_*`, `domain_*`, `ddns_*`, `subscription_expiry_timestamp_seconds` |
| Disk health | `smart_*` per host and disk |
| Indexer usage | `indexer_used`, `indexer_limit` (`host` beefy = Seerr bar, fastpi = audiobook bar) |

## Alert routing

`alertmanager/alertmanager.yml` (gitignored; template `alertmanager.yml.example`, same structure). Telegram layout: `alertmanager/templates/telegram.tmpl` (directory mount, edits live after an `amtool`-checked reload). Edit the live file in place (same inode), then `docker exec alertmanager amtool check-config /etc/alertmanager/alertmanager.yml && docker kill -s HUP alertmanager`.

| Alerts | Channel | When |
|---|---|---|
| `severity=critical` (edge, DNS, endpoints, disk/RAM critical, rollback failed, secret leak) | `critical`: Telegram + email, with resolved | at once, any time, repeat 12 h |
| `MalwareQuarantined`, `MalwareFound` | Telegram + email, no resolved | at once, any time |
| `DownloadCorrupt` (warning), `DownloadIntegrityErrors`, `DownloadIntegrityMetricsMissing` (info) | Telegram, no resolved | muted 22:00-07:00, text lists title, file, reason (`rules/antivirus.yml`) |
| `ContainerDown` of traefik, cloudflared, crowdsec, adguard*, authentik* | Telegram + email, no resolved | at once, any time |
| Intrusion signs: `SshLoginOutsideLan` (unknown source), `SshLoginUnexpectedUser`, `SecurityFileChanged`, `BeefyBackupSnapshotInFuture` | Telegram + email, no resolved | at once, any time (never muted) |
| `PlugSwitchedUnexpectedly`, `ServerPowerLost` (POSTed by Home Assistant, `Home-Assistant/config/packages/plug_watch.yaml`) | `telegram-power` (layout `tg.power`), no resolved | at once, any time, one message per event (label `at`) |
| `BeefyWakeFailed` 🆘 (critical), `BeefyWakeRecovered` ✅ (info) (POSTed by Beefy-Waker, `Beefy-Waker/app/recovery.py`) | `telegram-power` (layout `tg.power`), no resolved | at once, any time, one message per event (label `at`) |
| `AlertingHeartbeat` | email | every 28 days |
| `DeadMansSwitch` | healthchecks.io webhook (it alerts by Telegram + email) | every 4 min |
| other warnings | Telegram, no resolved | at once, muted 22:00-07:00, repeat 24 h |
| other info | Telegram, no resolved | at once, muted 22:00-07:00, repeat 7 d |
| `BeefyWakeLoop`, `TowerWakeLoop`, `RootkitWarning`, `SecurityScanStale`, `ClamavScanStale`, `BeefyAwakeLong` | Telegram, no resolved | once per episode, muted 22:00-07:00 |
| label `notify: digest` (50 rules: scanner/collector health, host warnings, CrowdSec hygiene, slow posture, VPN/tunnel SSH logins, `NewFixableImageVulnerability`, `AutoUpdateNightly`, `AudioLanguageNotFound`, `HostRebooted`, expiry/SMART exporter health) | no message (`null`), listed in `DailyDigest` | daily 06:30 |
| label `notify: weekly` (`ContainerImageUpdatesAvailable`, `UnraidUpdateAvailable`, `CriticalImageVulnerabilities`) | no message, figures in `WeeklyUpdateDigest` | Monday 05:00 |
| `DailyDigest`, `WeeklyUpdateDigest` | `telegram-digest` | 06:30 daily, Monday 05:00, never muted |
| `AlertNotificationsFailing{integration="telegram"}` | email | at once |
| any label `test=…` | `telegram-test`, marked 🧪, never email | only when sent on purpose |

- **Quiet hours** (`time_intervals: quiet-hours`, Europe/Zurich, DST-safe): muted sends are dropped; a group still firing at 07:00 is sent then, one that fired and cleared overnight is in the digest.
- **Daily digest** (`prometheus/rules/daily-digest.yml`): digest-only alerts and other alerts of the last 24 h (⏳ still firing / ✔️ cleared), new fixable CVEs grouped per CVE, nightly auto-update per host, hours beefy/tower were awake, beefy SSD/HDD used % and the last mover run, beefy queue-watchdog events (`beefy_watchdog_event_timestamp_seconds`, every kind of `queue-watchdog.py` as plain text, an unknown kind with `_` as spaces; all `indexer_rate_limited` events merged into one line "indexer paused (rate limit)" with the distinct indexer names, without " (Prowlarr)", and ×count), and only when something is due the expiry and disk section (see Expiry and disk health). Alerts silenced in Alertmanager are not listed as firing but as one line `🔇 n silenced: names` per alert section (`homelab:alert_silenced`, json-exporter module `alertmanager`). Lists capped (8/6/5/6/5/4) to stay under 4096 characters.
- **New alert rule:** pick its line above; give it `notify: digest` if it needs no action today.
- **Maintenance:** `Docker/_global/scripts/maintenance-silence.sh on [hours] [reason]` before batch or upgrade work, `off` after: silences ContainerCrashLooping, ContainerDown, ContainerUnhealthy, SecurityFileChanged, HostRebooted, SshLoginOutsideLan; the digest still lists them.
- **Tests:** no separate test chat exists, so 🧪 messages go to the alert group, only when sent on purpose (a POSTed alert with a `test` label, `oob-alert.sh --test`). To check the path without a message: `oob-alert.sh --check`.

```bash
python3 alertmanager/test_routing.py [alertmanager/alertmanager.yml]   # receivers via amtool + quiet-hour muting; default: the template
docker exec alertmanager amtool config routes test --config.file=/etc/alertmanager/alertmanager.yml alertname=X severity=warning
```

`AlertmanagerDown` cannot be delivered by the Alertmanager that is down: the cover is the container-exporter Telegram fallback, and for fastpi fully offline the healthchecks.io dead-man's switch.

## Usage per user

Dashboard `usage-per-user` (time range drives the "selected range" tables, "all time" tables ignore it). Collector `usage-collector/usage_collector.py`, nightly at 04:12 Europe/Zurich (`usage-collector.timer`, user `pi`; inside beefy's 03:55 to 04:26 maintenance wake, so Seerr and Jellyfin are reachable without waking it; run `sudo systemctl start usage-collector.service` for an on-demand refresh), writes InfluxDB bucket `usage` (retention infinite).

| Measurement | Source | Tags | Fields |
|---|---|---|---|
| `seerr_request` | Seerr `/api/v1/request` (paginated) | `user`, `media_type` (movie/tv) | `count`, `id` |
| `jellyfin_play` | Jellyfin activity log, start paired with stop | `user`, `kind` (film/episode/unknown) | `plays`, `seconds` |
| `abs_listen` | Audiobookshelf `playbackSessions` | `user` | `sessions`, `seconds` |

- InfluxDB, not Prometheus textfile: points carry their original timestamp, so history backfills and per-day sums work for any range. Re-runs overwrite the same points (idempotent).
- Seerr and Jellyfin: `usage_beefy.py` is piped to beefy over `ssh beefy-direct` and calls both APIs on localhost; the API keys are read on beefy and never copied. beefy asleep (TCP probe of `beefy.homelab:22` fails): skipped, nothing is woken, the next run catches up from the APIs' history. No Playback Reporting plugin is installed, so watch time = stop minus start, capped at the item's runtime; a start without stop counts as a play with 0 s after 6 h.
- `kind`: the Jellyfin item type when the item still exists. Deleted items are classified from the activity log name (`X is playing Title on Device`): `Series - Episode` means episode, plain title means film (heuristic, flagged `guessed`); an unreadable name is `unknown` (shown as "Unknown (deleted)"). Real kinds seen once are remembered in `~/.local/state/usage-collector/kinds.json` and win over a later guess.
- Tables: one row per user, columns Films, Series, (Unknown), Total (requests, watch time), Audiobooks (listening). Ebook and audiobook requests are not tracked yet, so those columns do not exist there.
- Audiobookshelf: read-only SQLite read of `absdatabase.sqlite` (only `username`, never the token column). Sessions of deleted accounts (userId NULL, ABS clears it when a user is deleted) are left out: the name is gone, so they cannot be attributed. No ABS API token exists and creating one needs an admin login; the table is stable, a schema change fails loudly (unit fails).
- Requests deleted in Seerr stay in the history. Users are labelled by name only, no emails.

```bash
sudo cp usage-collector/systemd/usage-collector.* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now usage-collector.timer
python3 usage-collector/test_usage.py
sudo systemctl start usage-collector.service && journalctl -u usage-collector -n 5
```

New token: `docker exec influxdb influx auth create -o myorg -d "usage collector write" --write-bucket <usage bucket id>`, file `secrets/usage_influx_token` mode 0400 owner `pi`.

## Image updates

| Services | Tier (`_global/auto-update.conf`) | Check |
|---|---|---|
| node-exporter, blackbox-exporter, blackbox-exporter-wan, json-exporter | `auto` (owner 2026-11-11) | `scripts/exporters-scraped.sh`: each exporter scraped by Prometheus since its restart, every such scrape `up` |
| prometheus, alertmanager, grafana, influxdb, telegraf | `notify` (the alert path itself) | by hand; backs up the Grafana + InfluxDB volumes |

## Secrets

Files in `secrets/` (gitignored, mode `0400`, owner = the reading container's uid), mounted via compose `secrets:`, never env values. How-to: `Docker/_global/docs/secrets-as-files.md`.

| File | Owner | Read by |
|---|---|---|
| `grafana_admin_password` | 65050 | `GF_SECURITY_ADMIN_PASSWORD__FILE` (only on first DB create) |
| `grafana_oauth_client_secret` | 65050 | `GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET__FILE` |
| `grafana_influx_token` | 65050 | `provisioning/datasources/influxdb.yml` `$__file{}`. Read-only token `grafana read (+usage …)`: read on buckets `rpi` + `homeassistant` + `usage` (all the dashboards query). A dashboard on a new bucket needs that bucket added to the token |
| `influxdb_admin_password` | 65020 | `DOCKER_INFLUXDB_INIT_PASSWORD_FILE` (only on first setup) |
| `usage_influx_token` | pi | `usage-collector`. Write-only token `usage collector write`: write on bucket `usage` |
| `telegraf_influx_token` | 65040 | `telegraf.conf` `@{docker_secretstore:telegraf_influx_token}` |
| `../alertmanager/secrets/*` | 65004 | `alertmanager.yml` `*_file` |
| InfluxDB operator token (`admin's Token`) | 65020, `0600` | not in `secrets/`: the influx CLI config `/etc/influxdb2/influx-configs` in the `influxdb` container (its anonymous volume). Admin work: `docker exec influxdb influx auth list` etc., no `--token` |

`provision-admin-sso.py` writes the OAuth client id into `.env` and the secret into `secrets/grafana_oauth_client_secret` (Authentik README "Re-running the provisioning").
