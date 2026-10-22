# Container escape-hardening (fastpi)

Goal: make a container escape very hard to turn into host takeover. Daemon-wide userns-remap was
REJECTED (see userns-remap-plan.md) — this is the per-container replacement. Levers, per stack:
`no-new-privileges` (Tier 1, done widely) → run off uid 1000 → non-root where the image allows →
`cap_drop:[ALL]`+minimal → `read_only`+tmpfs. Dedicated uid scheme: **65000+ range, never 1000**.

Edge/stateful restarts are machine.md yes-first → done only with owner home on LAN.

## uid-1000 (= `pi`/sudo on escape) — the priority
| Stack / container | New uid | Status | Notes |
|---|---|---|---|
| m4b-merge-dashboard | 65001 | ✅ done+verified | caddy, all-ro, read_only |
| avatar-picker | 65002 | ✅ done+verified | chowned 600 secrets to 65002 |
| claude-mockups-inbox | 65003 | ✅ done+verified | chowned ./answers; pi still reads them |
| alertmanager | 65004 | ✅ done+verified | chowned secrets + alertmanager_data volume; /-/healthy 200 |
| beefy-waker | 65005 | ✅ done+verified | host-net; chowned ./secrets; /key readable, serving :9001 |
| tower-waker | 65006 | ✅ done+verified | host-net; no secret mount; serving :9002, healthy |
| audiobookshelf | — | ⚠ careful | reads /mnt library (host uid 1101); uid change affects shared-mnt access |
| m4b-auto-merge | — | ⚠ careful | writes /mnt library+quarantine (shared uid 1101) |
| authentik-server | — | 🏠 home (EDGE/SSO) | |
| authentik-worker | — | 🏠 home (EDGE/SSO) | |

## root (uid 0; escape = host root) — reduce where possible
Done+verified non-root 2026-10-22: **stonks→65007**, **backdrop-carousel→65008** (both serve 200),
**sbb-easyride→65009** (pre-provided cert mounted ro + HOME=/tmp; serves 200; OIDC = user-spot-check).

Still root, in-repo, tractable next (test each, rollback to root on failure):
- autoheal×3 (antivirus/mouse/nzb) — talk to socket-proxy over TCP, no file deps → likely clean non-root.
- virustotal — reads `/scan` downloads owned 1101; non-root only if those are other-readable (verify).
- claude-mockups (caddy) — check its listen port before non-root (cap_net_bind if :80).
- whoami — trivial, but lives in the Traefik (edge) compose → treat as edge/home.
- blackbox-exporter — non-root + `cap_add: NET_RAW` for ICMP.

Must stay root but `cap_drop:[ALL]`+minimal + no-new-priv: adguard(:53), traefik(:80/443), crowdsec,
clamav(reads all uids), samba, gluetun(NET_ADMIN), qbittorrent/sabnzbd(/mnt 1101), influxdb/postgres(home).
loyalty-cards = PARKED, skip.

## NOT in this repo (do not edit here — locate their repo first)
`homelab-dashboard`, `wg-chores-app`, `wg-chores-sqliteweb` run on fastpi but are defined in another
repo (likely ~/landingpage or a wg-chores project). cloudflared stack also runs `cloudflare-ddns-minecraft`
+ `cloudflare-ddns-vpn` (account for these when hardening cloudflared).

## Already good (non-root, non-1000)
grafana(472), prometheus/node-exporter/json-exporter(65534), telegraf(999), languagetool(100), loyalty-sync(10001).

## docker.sock
Held ONLY by the 3 hardened socket-proxies (portainer-socket-proxy, socket-proxy-ro, socket-proxy-autoheal)
— consumers go through them, never the real socket. Keep it that way.
