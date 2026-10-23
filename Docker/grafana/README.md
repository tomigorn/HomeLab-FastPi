# Grafana

Monitoring stack: Grafana, Prometheus, Alertmanager, InfluxDB, Telegraf, exporters. Grafana: https://grafana.holy-grail.ch (Holy Grail, group `homelab-admins`).

## Dashboards

Provisioned from `provisioning/dashboards/*.json` into folder `fastpi`; edits to a file load within 30 s.

| Dashboard | uid | Shows |
|---|---|---|
| CrowdSec | `crowdsec-overview` | bans, attacks, bouncer and hub health (`Docker/CrowdSec/README.md`) |
| Updates & security | `updates-security` | OS/image updates, CVEs, ClamAV, rootkit/Lynis, CrowdSec versions, firing security alerts (`Server/4-Security-Monitoring/README.md`) |
| fastpi — RAM, containers & electricity | `fastpi-resources` | per-container RAM, plug power (InfluxDB) |
| LanguageTool — usage watch | `languagetool-watch` | LanguageTool usage |

## Container and reboot alerts

`container-exporter/container_exporter.py`, every minute (`container-exporter.timer`, root), writes `container_status.prom` for node-exporter. Rules: `prometheus/rules/containers.yml`, `prometheus/rules/host.yml`.

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
sudo cp container-exporter/systemd/container-exporter.* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now container-exporter.timer
python3 container-exporter/test_container_exporter.py
docker run --rm --network none --entrypoint sh -v "$PWD/prometheus":/w:ro -w /w/tests prom/prometheus:v3.15.1 -c 'promtool test rules *.yml'   # glob expands inside the container
docker kill -s HUP prometheus   # reload rules
```

## Host resource alerts

`prometheus/rules/host-resources.yml` (node-exporter, job `raspberry-pi`; disks ext4/xfs/btrfs/vfat). Warning and critical use disjoint ranges.

| Alert | Fires when | Severity |
|---|---|---|
| `HostFilesystemSpaceLow` / `…Critical` | < 15% free for 30 min / < 5% for 5 min | warning / critical |
| `HostFilesystemFillingUp` | < 40% free and the 6 h trend hits 0 within 24 h, for 1 h | warning |
| `HostFilesystemReadOnly` | a disk is mounted read-only for 2 min | critical |
| `HostInodesLow` / `…Critical` | < 10% inodes free for 30 min / < 5% for 5 min | warning / critical |
| `HostMemoryLow` / `…Critical` | MemAvailable < 10% for 10 min / < 5% for 5 min | warning / critical |
| `HostSwapHigh` | > 80% of swap used for 15 min | warning |
| `HostCpuHot` / `HostCpuThrottling` | CPU > 75 °C for 10 min / > 80 °C for 5 min | warning / critical |
| `HostNvmeHot` | NVMe at or over its own warning temperature for 10 min | warning |
| `HostLoadHigh` | load15 > 2 per core for 30 min | warning |
| `HostOomKill` | kernel OOM kill in the last 15 min | warning |

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
| `ContainerImageUpdatesAvailable` | `last_over_time(cup_updates_available[20m]) > 0` for 30 min; severity info, Telegram only, repeats weekly |
| `CupNotReporting` | `last_over_time(up{job="cup"}[20m]) == 0` for 1 h; Cup is scraped every 15m but a sample is only current for 5m, so a bare selector would never hold for `for:` |

`prometheus.yml`, `blackbox.yml` and `alertmanager.yml` are single-file bind mounts: an editor that replaces the file leaves the container on the old inode, so after editing them run `docker compose up -d --force-recreate <service>` instead of a HUP/reload.

## Endpoint probes

blackbox jobs in `prometheus/prometheus.yml`, rules in `prometheus/rules/public-endpoints.yml`. `blackbox-exporter` resolves `*.holy-grail.ch` through AdGuard to Traefik on the LAN (from a container IP, so outside `local-networks@file`).

| Job | Pass | Targets | Alert |
|---|---|---|---|
| `blackbox-public` | 200/301/302/401/403 | audiobookshelf, sso | `PublicEndpointDown`, `AllPublicEndpointsDown` |
| `blackbox-gated` | 302 to sso.holy-grail.ch | cup, claude-mockups, tracker, avatars | `PublicEndpointDown` |
| `blackbox-gated-wake` (15m) | 302 to sso.holy-grail.ch | requests (Seerr, behind `requests-wake`) | `WakeGatedEndpointNotGated` |
| `blackbox-lan-locked` | 403 | radarr, sonarr, prowlarr, bazarr, qbittorrent, sabnzbd, stonks, traefik, adguard | `LanLockedEndpointNotLocked` |
| `blackbox-wan-public` | 200/301/302/401 | audiobookshelf, sso | `PublicPathDown`, `CloudflareTunnelDown` |
| `blackbox-wan-gated` | 302 to sso.holy-grail.ch | cup, claude-mockups, tracker, avatars | `PublicPathDown`, `CloudflareTunnelDown` |
| `blackbox-wan-lan-locked` | 403 with Traefik's body `Forbidden` | stonks | `PublicPathDown`, `CloudflareTunnelDown` |

`blackbox-wan-*` run on `blackbox-exporter-wan` (uid 65010, read-only), which resolves through 1.1.1.1/9.9.9.9 and so goes through Cloudflare and the tunnel. Only hostnames with a public DNS record (radarr & co. have none). `CloudflareTunnelDown` = every Cloudflare probe fails while a LAN probe passes; it also fires when fastpi's internet is down.

## Media language (beefy)

`prometheus/rules/media-language.yml`, test `prometheus/tests/media-language_test.yml`. Source: beefy `Movie-Downloads/scripts/language-missing.py` → `security_scan.py media` (04:20 pull) → `media_language_beefy.prom`.

| Alert | Fires when | Severity |
|---|---|---|
| `AudioLanguageNotFound` | a Radarr/Sonarr title tagged `audio-swiss-german` waits 7 days for a Swiss German release (or a grab of it failed later); holds 5 days, so one Telegram per title and `failed` count | info |

The textfile stays on fastpi while beefy sleeps, so the series do not go stale; details in `HomeLab-BeefyServer` `Docker/Movie-Downloads/README.md`, "Swiss German not found alert".

## Alert routing

`alertmanager/alertmanager.yml` (gitignored; template `alertmanager.yml.example`). Check a route: `docker exec alertmanager amtool config routes test --config.file=/etc/alertmanager/alertmanager.yml alertname=X severity=info`.

| Match | Receiver |
|---|---|
| `WeeklyUpdateDigest` | `telegram-digest` |
| `AlertNotificationsFailing{integration="telegram"}` | `email` (a broken Telegram is not reported over Telegram) |
| `AudioLanguageNotFound` | `telegram-once` (no resolved message; grouped per app, title, failed) |
| `severity="info"` | `telegram` |
| `severity="heartbeat"` | `heartbeat` (email, 28 days) |
| everything else (warning, critical) | `admins` (email + Telegram) |

`AlertmanagerDown` cannot be delivered by the Alertmanager that is down: the cover is the container-exporter Telegram fallback, and for fastpi fully offline an external dead-man's switch (`Docker/_global/docs/healthchecks-deadman-switch.md`, not set up).

## Secrets

Files in `secrets/` (gitignored, mode `0400`, owner = the reading container's uid), mounted via compose `secrets:`, never env values. How-to: `Docker/_global/docs/secrets-as-files.md`.

| File | Owner | Read by |
|---|---|---|
| `grafana_admin_password` | 65050 | `GF_SECURITY_ADMIN_PASSWORD__FILE` (only on first DB create) |
| `grafana_oauth_client_secret` | 65050 | `GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET__FILE` |
| `grafana_influx_token` | 65050 | `provisioning/datasources/influxdb.yml` `$__file{}`. Read-only token `grafana read`: read on buckets `rpi` + `homeassistant` (all the dashboards query). A dashboard on a new bucket needs that bucket added to the token |
| `influxdb_admin_password` | 65020 | `DOCKER_INFLUXDB_INIT_PASSWORD_FILE` (only on first setup) |
| `telegraf_influx_token` | 65040 | `telegraf.conf` `@{docker_secretstore:telegraf_influx_token}` |
| `../alertmanager/secrets/*` | 65004 | `alertmanager.yml` `*_file` |
| InfluxDB operator token (`admin's Token`) | 65020, `0600` | not in `secrets/`: the influx CLI config `/etc/influxdb2/influx-configs` in the `influxdb` container (its anonymous volume). Admin work: `docker exec influxdb influx auth list` etc., no `--token` |

`provision-admin-sso.py` still writes `GRAFANA_OAUTH_CLIENT_SECRET` into `.env`; move it into `secrets/grafana_oauth_client_secret` after a re-provision.
