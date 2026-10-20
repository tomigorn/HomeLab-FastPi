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
cd prometheus && docker run --rm --entrypoint promtool -v "$PWD":/w -w /w/tests prom/prometheus:latest test rules containers_test.yml host_test.yml
docker kill -s HUP prometheus   # reload rules
```
