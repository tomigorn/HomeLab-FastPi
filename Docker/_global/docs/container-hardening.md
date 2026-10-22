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
| alertmanager | 65004? | ⏳ todo (safe-ish) | monitoring; chown its data volume |
| beefy-waker | 65005? | ⏳ todo | host-net; chown ./secrets |
| tower-waker | 65006? | ⏳ todo | host-net; chown ./secrets |
| audiobookshelf | — | ⚠ careful | reads /mnt library (host uid 1101); uid change affects shared-mnt access |
| m4b-auto-merge | — | ⚠ careful | writes /mnt library+quarantine (shared uid 1101) |
| authentik-server | — | 🏠 home (EDGE/SSO) | |
| authentik-worker | — | 🏠 home (EDGE/SSO) | |

## root (uid 0; escape = host root) — reduce where possible
Stateless, likely non-root-able (test each; may need chown of ./data or a writable tmpfs):
stonks, backdrop-carousel, sbb-easyride (writes /app cert → may need tmpfs), claude-mockups(caddy :80),
homelab-dashboard, wg-chores-app, wg-chores-sqliteweb, blackbox-exporter(needs CAP_NET_RAW), virustotal.
Must stay root but `cap_drop:[ALL]`+minimal + no-new-priv: adguard(:53), traefik(:80/443), crowdsec,
clamav(reads all uids), samba, gluetun(NET_ADMIN), qbittorrent/sabnzbd(/mnt 1101), influxdb/postgres(home),
autoheal×3 (talk to socket-proxy). loyalty-cards = PARKED, skip.

## Already good (non-root, non-1000)
grafana(472), prometheus/node-exporter/json-exporter(65534), telegraf(999), languagetool(100), loyalty-sync(10001).

## docker.sock
Held ONLY by the 3 hardened socket-proxies (portainer-socket-proxy, socket-proxy-ro, socket-proxy-autoheal)
— consumers go through them, never the real socket. Keep it that way.
