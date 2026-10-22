# Container hardening (fastpi)

State 2026-10-22, verified from `/proc/<pid>/status` of every process (not `docker exec id`).

## Rules for every container
| Rule | How |
|---|---|
| Never uid/gid 1000 (`pi`, sudo + docker) | dedicated `user: "650NN:650NN"`, next free in the map below |
| No root where the image allows it | `user:`; low ports via `sysctls: net.ipv4.ip_unprivileged_port_start: "0"` (bridge) or `NET_BIND_SERVICE` (host-net) |
| No capabilities | `cap_drop: [ALL]`, `cap_add` only what a test proved is needed |
| No privilege gain | `security_opt: [no-new-privileges:true]` |
| Read-only where possible | `read_only: true` + `tmpfs` for `/tmp` / `/run` |
| Shared data only through a shared group | `group_add`, setgid dir + default ACL; everything else alone in its own group |
| Never the Docker socket | only the 3 socket proxies hold it (below) |

linuxserver images: use their non-root mode (`user:` + `tmpfs: /run:uid=…,gid=…,exec`) when the image readme lists "Non-Root Operation". Otherwise mount `_global/lsio-init/drop-users-group.sh` (removes `abc` from `users` = gid 1000).

## uid map
| uid | Container | Extra groups | Caps | ro |
|---|---|---|---|---|
| 65001 | m4b-merge-dashboard | | NET_BIND_SERVICE | ✅ |
| 65002 | avatar-picker | | | ✅ |
| 65003 | claude-mockups-inbox | | | ✅ |
| 65004 | alertmanager | | | |
| 65005 / 65006 | beefy-waker / tower-waker | | | |
| 65007 | stonks | | | |
| 65008 | backdrop-carousel | | | |
| 65009 | sbb-easyride-taxreport | | | |
| 65011–65013 | autoheal-antivirus / -mouse / -nzb | | | |
| 65014 | virustotal | | | |
| 65015 | blackbox-exporter | | | |
| 65016 | claude-mockups | | NET_BIND_SERVICE | |
| 65017 | audiobookshelf | 1100 | | ✅ |
| 65018 | m4b-auto-merge | 1100 | | |
| 65019 | authentik-server, authentik-worker | | | |
| 65020 | influxdb | | | |
| 65021 | duckdns (app; PID1 root, see below) | | | |
| 65022 | noip | | | |
| 65024 / 65025 | Cup / cup-agent-fastpi | | | |
| 65026 | traefik | | | |
| 65027 | socket-proxy-unix | | | |
| 65028 | portainer-socket-proxy-unix | | | |
| 65030 | portainer | 65028 | | |
| 65032 | crowdsec | | | |
| 65033 | adguardhome (host-net) | | NET_BIND_SERVICE | |
| 65034 | homelab-dashboard (repo `~/landingpage`) | | | ✅ |
| 65035 / 65036 | wg-chores-app / -sqliteweb (repo `~/Documents/development/WG-Chores`) | 65037 | | ✅ |
| 65038 | languagetool | | | |
| 65039 | clamav | 1100, 65046 | DAC_READ_SEARCH | |
| 65040 | telegraf | | | |
| 65041 / 65042 | mousehole / port_updater | | | |
| 65043 / 65044 / 65045 | prometheus / node-exporter / json-exporter | | | |
| 65047 / 65048 / 65049 | socket-proxy-ro / socket-proxy-autoheal / portainer-socket-proxy | 991 (docker) | | ✅ |
| 65050 | grafana | | | |
| 1101:1100 | sabnzbd, qbittorrent (lsio non-root) | | | |
| 70 | authentik-postgresql | | | |
| 65532 | cloudflared (image default) | | | |

Shared groups: `1100` = sambashare (media library, no sudo/docker), `65037` = wg-chores data, `65046` = writers of `/var/lib/node-exporter/textfile`, `65028` = Portainer socket bridge.
Free: 65010, 65023, 65029, 65031, 65051+.

## Root by design (cap_drop ALL + minimal caps + no-new-privileges)
| Container | Caps | Why it stays root |
|---|---|---|
| duckdns | CHOWN, DAC_OVERRIDE, FOWNER, SETUID, SETGID | image has no non-root mode (tested 2026-10-22: s6 init fails); app runs as 65021 |
| homeassistant | CHOWN, DAC_OVERRIDE, FOWNER, SETUID, SETGID, NET_RAW | official image has no supported non-root mode (bluetooth/dbus, pip into /config) |
| gluetun_nzb, gluetun_mouse | NET_ADMIN, NET_RAW, NET_BIND_SERVICE, DAC_OVERRIDE, CHOWN | creates tun + iptables; no non-root mode |
| samba | NET_BIND_SERVICE, SETUID, SETGID, KILL, CHOWN, FOWNER, DAC_OVERRIDE, SYS_CHROOT | smbd switches to each user; avahi chroots |
| WireGuard-VPN | NET_ADMIN, NET_RAW | wg interface + iptables |
| loyalty-cards / loyalty-sync | untouched | stack PARKED |

## Docker socket
Only `socket-proxy-ro`, `socket-proxy-autoheal`, `portainer-socket-proxy` mount it (ro), non-root via group 991. Their entrypoint is overridden to run haproxy on the shipped template (`BIND_CONFIG: ":2375"`) because the upstream entrypoint writes into a root-owned dir. After an image bump: check `docker logs` and that an allowed endpoint returns 200 and a denied one 403.

## Host changes (not in git; recreate on rebuild)
| What | Value |
|---|---|
| `/etc/docker/daemon.json` | `{"dns":["192.168.1.2"]}` (containers resolve through AdGuard; needs `systemctl restart docker`) |
| `/var/lib/node-exporter/textfile` | `pi:65046`, mode 2775 |
| `/etc/modules-load.d/wireguard.conf` | `wireguard` (WireGuard-VPN has no SYS_MODULE, the host loads the module) |
| `Docker/grafana/alertmanager/secrets/telegram_bot_token` | `65004:pi`, 640 (alertmanager owns it, `oob-alert.sh` reads it as pi) |
| Traefik secrets (`dynamic/avatar-picker-secret.yml`, `dynamic/languagetool-token.yml`, `secrets/crowdsec_lapi_key`) | `pi:65026`, 640 |
| Data dirs / volumes | owned by the uid in the map |

## Not done, on purpose
- userns-remap: little gain over the above, see `userns-remap-recipe.md`.
- duckdns: could be replaced by a tiny non-root curl container; kept the standard image.
