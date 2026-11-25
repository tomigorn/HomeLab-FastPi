# Network IPAM plan (FB-16, FB-17): prepared, attended

State 2026-11-25: 7 compose networks have no declared subnet (FB-16); no network has an `ip_range`, so every pinned IP sits in the dynamic pool (FB-17).

Why not applied: compose stores a `com.docker.compose.config-hash` label on each network (`docker network inspect traefik_home -f '{{json .Labels}}'`). Adding `ipam` changes that hash, so the next `docker compose up` wants to recreate the network, which stops every container on it. All of them are yes-first (edge) or need a planned window.

## FB-16: declare the live subnet
| Project | Network key | Live name | Add to compose |
|---|---|---|---|
| Authentik | `authentik_internal` | `authentik_authentik_internal` | `ipam: {config: [{subnet: 172.30.0.0/16}]}` |
| CrowdSec | `crowdsec` | `crowdsec` | `ipam: {config: [{subnet: 192.168.32.0/20}]}` |
| Docker-Socket-Proxy | `socket_proxy` | `socket_proxy` | `ipam: {config: [{subnet: 192.168.16.0/20}]}` |
| Docker-Socket-Proxy | `socket_proxy_heal` | `socket_proxy_heal` | `ipam: {config: [{subnet: 192.168.96.0/20}]}` |
| Docker-Socket-Proxy | `socket_proxy_portupdater` | `socket_proxy_portupdater` | `ipam: {config: [{subnet: 192.168.112.0/20}]}` |
| Traefik | `traefik_metrics` | `traefik_metrics` | `ipam: {config: [{subnet: 192.168.128.0/20}]}` |
| cloudflared | `default` | `infra__cloudflare_default` | `ipam: {config: [{subnet: 172.20.0.0/16}]}` (`host-input-guard.sh` and `authorized_keys from=` rely on it) |

## FB-17: `ip_range` outside the pins
Proposed range = the first free aligned block in the upper part of the subnet, no pin inside. `/29` networks have no room (6 hosts, keep as is).

| Network | Subnet | Pins | Proposed `ip_range` | Class |
|---|---|---|---|---|
| `activity_influx` | 10.24.40.8/29 | 10.24.40.10, 10.24.40.11 | `None` | non-edge |
| `activity_metrics` | 10.24.40.0/29 | 10.24.40.2, 10.24.40.3 | `None` | non-edge |
| `antivirus_antivirus_network` | 10.24.34.0/24 | 10.24.34.2, 10.24.34.3 | `10.24.34.128/25` | non-edge |
| `audiobook-requests_egress` | 10.24.26.0/28 | 10.24.26.2, 10.24.26.3 | `10.24.26.8/29` | non-edge |
| `authentik_authentik_internal` | 172.30.0.0/16 | 172.30.0.2, 172.30.0.3, 172.30.0.4, 172.30.0.5 | `172.30.128.0/17` | edge |
| `claude-mockups_mockups_internal` | 172.29.0.0/16 | 172.29.0.2, 172.29.0.3 | `172.29.128.0/17` | non-edge |
| `crowdsec` | 192.168.32.0/20 | 192.168.32.2, 192.168.32.3 | `192.168.40.0/21` | edge |
| `cup_cup_agents` | 172.31.0.0/16 | 172.31.0.2, 172.31.0.3 | `172.31.128.0/17` | non-edge |
| `infra__cloudflare_default` | 172.20.0.0/16 | 172.20.0.2, 172.20.0.3 | `172.20.128.0/17` | edge |
| `m4b-auto-merge_default` | 192.168.64.0/20 | 192.168.64.2 | `192.168.72.0/21` | non-edge |
| `m4b-merge-dashboard_default` | 192.168.48.0/20 | 192.168.48.2 | `192.168.56.0/21` | non-edge |
| `monitoring__grafana_default` | 192.168.208.0/20 | 192.168.208.2, 192.168.208.3, 192.168.208.4, 192.168.208.5,  | `192.168.216.0/21` | non-edge |
| `mouse_mouse_network` | 10.24.32.0/24 | 10.24.32.2, 10.24.32.3 | `10.24.32.128/25` | non-edge |
| `portainer_socket` | 192.168.80.0/20 | 192.168.80.2, 192.168.80.3, 192.168.80.4 | `192.168.88.0/21` | non-edge |
| `sbb-easyride-taxreport_app-network` | 192.168.144.0/20 | 192.168.144.2 | `192.168.152.0/21` | non-edge |
| `socket_proxy` | 192.168.16.0/20 | 192.168.16.2, 192.168.16.3, 192.168.16.4 | `192.168.24.0/21` | non-edge |
| `socket_proxy_heal` | 192.168.96.0/20 | 192.168.96.2, 192.168.96.3, 192.168.96.4 | `192.168.104.0/21` | non-edge |
| `socket_proxy_portupdater` | 192.168.112.0/20 | 192.168.112.2, 192.168.112.3 | `192.168.120.0/21` | non-edge |
| `traefik_authentik` | 10.24.15.0/28 | 10.24.15.2, 10.24.15.3 | `10.24.15.8/29` | edge |
| `traefik_crowdsec` | 10.24.11.0/28 | 10.24.11.2, 10.24.11.3 | `10.24.11.8/29` | edge |
| `traefik_home` | 10.24.22.0/28 | 10.24.22.2, 10.24.22.3 | `10.24.22.8/29` | edge |
| `traefik_loyalty_cards` | 10.24.20.0/28 | 10.24.20.2, 10.24.20.3 | `10.24.20.8/29` | edge |
| `traefik_loyalty_sync` | 10.24.21.0/28 | 10.24.21.2, 10.24.21.3 | `10.24.21.8/29` | edge |
| `traefik_metrics` | 192.168.128.0/20 | 192.168.128.2, 192.168.128.3 | `192.168.136.0/21` | edge |
| `traefik_mouse` | 10.24.25.0/28 | 10.24.25.2, 10.24.25.3, 10.24.25.4, 10.24.25.5, 10.24.25.6 | `10.24.25.8/29` | edge |
| `traefik_portainer` | 10.24.7.0/28 | 10.24.7.3, 10.24.7.7 | `10.24.7.8/29` | edge |
| `traefik_proxy` | 172.24.0.0/16 | 172.24.0.2, 172.24.0.3, 172.24.0.4, 172.24.0.5, 172.24.0.6,  | `172.24.64.0/18` | edge |
| `traefik_stonks` | 10.24.23.0/28 | 10.24.23.2, 10.24.23.3 | `10.24.23.8/29` | edge |
| `traefik_wg` | 10.24.5.0/28 | 10.24.5.3, 10.24.5.5 | `10.24.5.8/29` | edge |
| `traefik_wg_chores` | 10.24.24.0/28 | 10.24.24.2, 10.24.24.3, 10.24.24.4 | `10.24.24.8/29` | edge |

Hand-made networks (no compose): `traefik_proxy`, `traefik_mouse`. Their create commands in `Docker/Traefik/README.md` get `--ip-range` when they are recreated.

## Apply (attended, one project at a time, edge only with the owner's yes)
1. Add `ipam.config[0].subnet` (FB-16) and `ip_range` (FB-17) to the network in the project's compose.
2. `docker compose config -q` → valid.
3. `Docker/_global/scripts/update-project.sh <Project> recreate` in a quiet window; compose asks to recreate the network (all containers on it stop briefly).
4. Check: `docker network inspect <net> -f '{{json .IPAM.Config}}'` shows subnet and range; `docker logs traefik --since 5m | grep -i error` empty; `Docker/_global/scripts/smoke-test.sh` green.

Rollback: revert the compose change and recreate again (the network gets the old config back).
