# CrowdSec

Reads Traefik's access log, bans attackers; the Traefik bouncer plugin
(`Traefik/traefik/dynamic/crowdsec.yml`) enforces the bans on every public route.

## Dashboard

**Grafana > fastpi > CrowdSec** - https://grafana.holy-grail.ch/d/crowdsec-overview
(Authentik group `homelab-admins`, LAN/VPN only - inherited from Grafana.)

Data path: CrowdSec metrics endpoint `crowdsec:6060` (docker network `crowdsec`
only, nothing published) -> Prometheus job `crowdsec` (30 s) -> Grafana.
Prometheus joins the `crowdsec` network for this (`grafana/docker-compose.yaml`).
Blocked/all request panels use Traefik's own metrics (job `traefik`).

| Panel | Meaning |
|---|---|
| Active bans | IPs banned right now (community blocklist + my own) |
| Bans from my own logs | Bans CrowdSec decided from attacks on this server |
| Blocked requests (24h) | HTTP 403s on `websecure`; almost all are bouncer blocks |
| Blocked vs all requests | 403 rate against total traffic |
| Responses by status class | 3xx = Authentik redirects, 404 = scanners, 403 = blocked |
| Alerts by scenario / Attacks detected | Which attack patterns fire (probing, CVE scans, WordPress...) |
| Log lines read/parsed/unparsed | Unparsed > 0 for long = Traefik log format changed, detection blind |
| Bouncer queries | Traefik asking CrowdSec "is this IP banned?"; flat zero = not enforcing |

Not in Prometheus (so not on the dashboard): top attacking IPs, countries, ASNs, and the
bouncer's exact "dropped requests" counter. Use the CLI:
`docker exec crowdsec cscli alerts list`, `cscli decisions list`, `cscli metrics`.

Why a custom dashboard: the official `crowdsecurity/grafana-dashboards` (MIT) were last
updated in 2023 for CrowdSec 1.5 (legacy graph panels, renamed metrics, no bouncer data),
so the JSON in `grafana/provisioning/dashboards/crowdsec.json` is built on the current
(v1.8) metric names instead. Edit it in Grafana or the file; the provisioner reloads
within 30 s. "Attacks detected (24h)" fills in after Prometheus has history.

## Optional: CrowdSec Console
https://app.crowdsec.net is a free cloud dashboard (map, per-IP alerts). Enrolling
(`cscli console enroll <key>`) sends alert metadata (attacker IPs, scenarios, timestamps)
to CrowdSec's servers. Not enabled.
