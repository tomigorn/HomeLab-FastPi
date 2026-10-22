# Container escape-hardening (fastpi)

> **DNS / container egress (fixed 2026-10-22).** `/etc/docker/daemon.json` (a host file, NOT in git) now
> contains `{ "dns": ["192.168.1.2"] }` — the host LAN IP where AdGuard listens. Before this, bridge
> containers were handed the router (192.168.1.1) which doesn't recurse, so container DNS + image builds
> failed. This one line fixes both runtime and builds, keeps every container behind AdGuard. Requires a
> `sudo systemctl restart docker` to take effect (done 2026-10-22, whole homelab bounced + verified: SSO
> canary OK, all 56 containers back, `apk` in a fresh container works). AdGuard `allowed_clients: []` (all
> allowed) so no ACL change was needed. **If fastpi is ever rebuilt, recreate this file.**

> **ROOT-HARDENING IS DEFERRED until AFTER the userns-remap migration** (user decision 2026-10-22): the
> migration changes the whole uid/cap picture, so re-doing cap_drop/non-root first would be wasted. The
> remaining root-hardening list is at the bottom of this doc — revisit it post-migration. See
> `userns-remap-recipe.md` for the migration plan.


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
| audiobookshelf | 65017 | ✅ done+verified | kept group_add 1100 (ACL); chowned config+metadata; healthy, DB intact, library rw ok |
| m4b-auto-merge | — | ⛔ EXCEPTION (stays 1000) | compose documents a hard uid-1000 dependency: it renames library files owned by uid 1000, and the image's `merger` user + `/home/merger/.ssh` + ssh keys assume 1000. Moving it needs a dedicated supervised session (verify the merge pipeline + beefy SSH after). |
| authentik-server | — | 🏠 home (EDGE/SSO) | |
| authentik-worker | — | 🏠 home (EDGE/SSO) | |

## root (uid 0; escape = host root) — reduce where possible
Done+verified non-root 2026-10-22: **stonks→65007**, **backdrop-carousel→65008** (both serve 200),
**sbb-easyride→65009** (pre-provided cert mounted ro + HOME=/tmp; serves 200; OIDC = user-spot-check).

More done+verified 2026-10-22: autoheal×3→65011/65012/65013 (reach socket-proxy, ping 200),
virustotal→65014 (reads /scan, downloads are other-readable), blackbox-exporter→65015 (modules are
http/tcp/dns only — NO NET_RAW needed; actively probing).

Still root, remaining:
- claude-mockups (caddy) — DEFERRED: binds :80 AND writes its config/data dir → non-root needs
  cap_add NET_BIND_SERVICE + a writable tmpfs/XDG dirs. Own small batch.
- whoami — lives in the Traefik (edge) compose → edge/home.
- cap_drop:[ALL]+minimal on the must-stay-root set (careful, each needs its cap list): clamav, samba,
  gluetun(NET_ADMIN), qbittorrent/sabnzbd — these are the media/download pipeline, verify after each.
- EDGE/stateful (home): adguard, traefik, crowdsec, authentik×2, influxdb, postgres, cloudflared, WireGuard.

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
