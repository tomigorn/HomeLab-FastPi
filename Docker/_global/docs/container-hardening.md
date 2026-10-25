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
| Never the Docker socket | only the socket proxies hold it (below) |

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
| 65010 | blackbox-exporter-wan | | | ✅ |
| 65011–65012 | autoheal-antivirus / -mouse | | | |
| 65014 | virustotal | | | |
| 65015 | blackbox-exporter | | | |
| 65016 | claude-mockups | | NET_BIND_SERVICE | |
| 65017 | audiobookshelf | 1100 | | ✅ |
| 65018 | m4b-auto-merge | 1100 | | |
| 65019 | authentik-server, authentik-worker | | | |
| 65020 | influxdb | | | |
| 65021 | duckdns (app; PID1 root, see below) | | | |
| 65022 | noip | | | |
| 65023 / 65024 / 65025 | cup-refresh / Cup / cup-agent-fastpi | | | |
| 65026 | traefik | | | |
| 65027 | socket-proxy-unix | | | |
| 65028 | portainer-socket-proxy-unix | | | |
| 65030 | portainer | 65028 | | |
| 65032 | crowdsec | | | |
| 65033 | adguardhome (host-net) | | NET_BIND_SERVICE | |
| 65034 | homelab-dashboard (repo `~/landingpage`) | | | ✅ |
| 65035 / 65036 | wg-chores-app / -sqliteweb (repo `~/Documents/development/WG-Chores`) | 65037 | | ✅ |
| 65038 | languagetool | | | |
| 65039 | clamav (no caps: a non-root uid gets no effective caps, `DAC_READ_SEARCH` was inert) | 1100, 65046 | | |
| 65040 | telegraf | | | |
| 65041 / 65042 | mousehole / port_updater | | | |
| 65043 / 65044 / 65045 | prometheus / node-exporter / json-exporter | | | |
| 65047 / 65048 / 65049 / 65051 | socket-proxy-ro / socket-proxy-autoheal / portainer-socket-proxy / socket-proxy-portupdater | 991 (docker) | | ✅ |
| 65050 | grafana | | | |
| 65052 | server-specs | | NET_BIND_SERVICE | ✅ |
| 1101:1100 | sabnzbd, qbittorrent (lsio non-root) | | | |
| 70 | authentik-postgresql | | | |
| 65532 | cloudflared (image default) | | | |

Shared groups: `1100` = sambashare (media library, no sudo/docker), `65037` = wg-chores data, `65046` = writers of `/var/lib/node-exporter/textfile`, `65028` = Portainer socket bridge.
Free: 65013 (was autoheal-nzb), 65029, 65031, 65053+.

## Root by design (cap_drop ALL + minimal caps + no-new-privileges)
| Container | Caps | Why it stays root |
|---|---|---|
| duckdns | CHOWN, DAC_OVERRIDE, FOWNER, SETUID, SETGID | image has no non-root mode (tested 2026-10-22: s6 init fails); app runs as 65021 |
| homeassistant | CHOWN, DAC_OVERRIDE, FOWNER, SETUID, SETGID, NET_RAW | official image has no supported non-root mode (bluetooth/dbus, pip into /config) |
| gluetun_mouse (also carries sabnzbd) | NET_ADMIN, NET_RAW, NET_BIND_SERVICE, DAC_OVERRIDE, CHOWN | creates tun + iptables; no non-root mode |
| samba | NET_BIND_SERVICE, SETUID, SETGID, KILL, CHOWN, FOWNER, DAC_OVERRIDE, SYS_CHROOT | smbd switches to each user; avahi chroots |
| WireGuard-VPN | NET_ADMIN, NET_RAW | wg interface + iptables |
| clamav-hostscan | DAC_READ_SEARCH, DAC_OVERRIDE, CHOWN | weekly host scan reads everything (`/:/host:ro`); non-root cannot use DAC_READ_SEARCH. Safe because `network_mode: none`, read-only root fs, writes only state + textfile; the always-on `clamav` no longer mounts the host root |
| loyalty-cards / loyalty-sync | untouched | stack PARKED |

## Images
- Locally built images (`*-local`, `*:local`): base image tracking and the per-image rebuild routine are in `Docker/Cup/README.md`, Locally built images.

## Docker socket
Only `socket-proxy-ro`, `socket-proxy-autoheal`, `socket-proxy-portupdater`, `portainer-socket-proxy` mount it (ro), non-root via group 991. Their entrypoint is overridden to run haproxy directly (`BIND_CONFIG: ":2375"`) because the upstream entrypoint writes into a root-owned dir. After an image bump: check `docker logs` and that an allowed endpoint returns 200 and a denied one 403.

| Proxy | Network | Allows | Consumers |
|---|---|---|---|
| `socket-proxy-ro` | `socket_proxy` | GET containers, images, info, version (POST=0) | telegraf, Cup (via `socket-proxy-unix`) |
| `socket-proxy-autoheal` | `socket_proxy_heal` | GET only the label-scoped unhealthy list (`autoheal-mouse`/`autoheal-antivirus`); POST `/containers/{64-hex id}/restart` (autoheal addresses by ID, names are 403) | autoheal-mouse, autoheal-antivirus |
| `socket-proxy-portupdater` | `socket_proxy_portupdater` | POST start/stop/restart of `qbittorrent_mouse`, `mousehole`, `sabnzbd`, `gluetun_mouse` by name; GET inspect `gluetun_mouse`; everything else 403 | port-updater |

- `socket-proxy-autoheal` and `socket-proxy-portupdater` run their own allow-lists (`Docker-Socket-Proxy/autoheal-haproxy.cfg`, `portupdater-haproxy.cfg`): in 0.3.0 the template denies every POST before `ALLOW_RESTARTS` is evaluated, so `POST=0` + `ALLOW_RESTARTS=1` returns 403 on restart. Create, exec, kill, update, logs, images, volumes are 403. Re-test after an image bump.
- `socket_proxy_heal` and `socket_proxy_portupdater` are created by `Docker/Docker-Socket-Proxy` (like `socket_proxy`), `internal: true`, `external: true` in the other stacks. Bring Docker-Socket-Proxy up first.
- Default-deny: edge containers (Traefik, Authentik, CrowdSec, AdGuard, cloudflared, WireGuard) are in no allow-list. New autoheal-labelled container: add the label `autoheal-<stack>=true`, nothing else (extend the regex in `autoheal-haproxy.cfg` for a new label name). New container for port-updater: add its name to the group in `portupdater-haproxy.cfg`. After a cfg change `docker compose up -d --force-recreate <proxy>` (bind-mounted file), then check a listed name returns non-403 (404/204) and `traefik` returns 403.

## Host changes (not in git; recreate on rebuild)
| What | Value |
|---|---|
| `/etc/docker/daemon.json` | `dns: ["192.168.1.2"]` (containers resolve through AdGuard), `log-driver: json-file` + `log-opts: {max-size: 10m, max-file: 3}`, `live-restore: true` (needs `systemctl restart docker`; log limits apply only to containers created afterwards). `userland-proxy` stays default `true`: `false` (tried 2026-10-24, reverted) made host requests arrive at Traefik as `172.24.0.1` → LAN-only routes 403, no security gain |
| `/boot/firmware/cmdline.txt` | `apparmor=1 security=apparmor` appended (2026-10-24, reboot); containers run the `docker-default` profile |
| `/etc/iptables/rules.v4` | only the DOCKER-USER guard, written by `sudo _global/scripts/docker-user-lan-guard.sh --persist`. Never `netfilter-persistent save`: it freezes Docker's per-bridge rules, which return at boot for deleted bridges and drop traffic to reused container IPs (Cup → agent broke 2026-10-24) |
| `/var/lib/node-exporter/textfile` | `pi:65046`, mode 2775 |
| `/etc/ssh/sshd_config.d/20-access.conf` | `AllowUsers pi`, no X11/agent forwarding, `MaxAuthTries 3` (TCP forwarding stays for `ssh -L`); beefy's key into fastpi removed (fastpi → beefy only) |
| user `deploy` | locked, shell nologin, out of the docker group, key parked as `authorized_keys.disabled-20261024` (Jenkins stopped) |
| autologin | off: lightdm `autologin-user` commented, tty1 override moved to `/root/disabled-20261024/` |
| `/etc/sysctl.d/90-hardening.conf` | `kernel.kptr_restrict = 1`, `kernel.dmesg_restrict = 1` (no kernel pointers / dmesg for unprivileged users), `net.ipv4.conf.{all,default}.send_redirects = 0`, `net.ipv4.conf.all.log_martians = 1`; `net.ipv4.conf.{all,default}.rp_filter = 2` (loose: strict breaks Docker/WireGuard asymmetric paths), `kernel.sysrq = 0` |
| unused services | `cups-browsed`, `ModemManager` disabled (2026-10-24; no printer, no modem) |
| `/etc/modules-load.d/wireguard.conf` | `wireguard` (WireGuard-VPN has no SYS_MODULE, the host loads the module) |
| `Docker/grafana/alertmanager/secrets/telegram_bot_token` | `65004:pi`, 640 (alertmanager owns it, `oob-alert.sh` reads it as pi) |
| Traefik secrets (`dynamic/avatar-picker-secret.yml`, `dynamic/languagetool-token.yml`, `secrets/crowdsec_lapi_key`) | `pi:65026`, 640 |
| Data dirs / volumes | owned by the uid in the map |

## Not done, on purpose
- userns-remap: little gain over the above, see `userns-remap-recipe.md`.
- duckdns: could be replaced by a tiny non-root curl container; kept the standard image.
