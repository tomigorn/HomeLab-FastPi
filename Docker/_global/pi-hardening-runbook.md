# FastPi Phase-2 Hardening Runbook

**Started:** 2026-06-07
**Owner agent + user:** tomigorn
**Single source of truth.** Update the STATUS pointer and COMMAND LOG *before* running each operational command, so a crashed/closed session can resume from exactly here.

Related: incident root-cause is in agent memory `pi-host-freeze-and-hardening.md`.

---

## Why (context)

FastPi froze 2026-06-07 (kernel alive / userspace dead, needed a hard power-cycle). Root cause = multi-factor memory-pressure livelock: OpenNebula crash-loop (now deleted) + a runaway Claude Code TUI flooding journald + no memory-cgroup containment + tiny swap + **no watchdog to auto-recover**. Phase-1 (done earlier): deleted OpenNebula, swap 200 MB→2 GB, memory cgroup re-enabled. This runbook = Phase-2 resilience hardening.

## Decisions locked with user

- mem_limit philosophy = **generous safety backstop** (limits well above observed usage; only a pathological runaway gets OOM-killed; healthy containers never hit them).
- Careful **per-service** pass; verify each works before moving on. Remote-access stack done LAST.
- Minimize reboots. **Result: ZERO reboots needed** — everything applies live.

## IMPORTANT correction (verified 2026-06-07)

The earlier-planned "cmdline.txt cleanup" is **DROPPED — false premise.** `cgroup_disable=memory numa=fake=8 numa_policy=interleave system_heap.max_order=0` are **Raspberry Pi 5 FIRMWARE-injected defaults** (in `/proc/cmdline` but in NO file under `/boot/firmware`; confirmed by grep + bare backup `cmdline.txt.bak-20260607-pre-harden`). They are NOT OpenNebula leftovers and cannot be removed via `cmdline.txt`. The appended `cgroup_enable=memory cgroup_memory=1` is the correct, standard override for the firmware's `cgroup_disable=memory`. `cmdline.txt` is already correct — leave it. No reboot required.

---

## ROADMAP

- [x] **Phase A — Runbook** (this file) created. (commit in Phase E)
- [x] **Phase B — journald hardening** — DONE & verified. Disk 3.6G→984M; config live.
- [x] **Phase C — Watchdog** — DONE & verified LIVE. wdctl Timeleft ticking @14s; journal "Watchdog running with a hardware timeout of 14s." Fixes the power-cycle problem.
- [x] **Phase D — Per-container mem_limits** — DONE. 44/46 running containers limited + verified. 2 deferred (loyalty-cards-app @ /home/deploy). vault edited (not running). Also fixed a pre-existing latent bug: landingpage healthcheck used `http://localhost/` (busybox wget hit IPv6 ::1 → refused, nginx is IPv4-only) → changed to `http://127.0.0.1/`; now healthy.
- [x] **Phase E — Final verification** — DONE. 0 unhealthy, 0 restarting, watchdog armed, 2.7 GiB available, journal 992M. Commit: PENDING user (changes on disk, uncommitted).

## FINAL STATE 2026-06-07
- Watchdog armed (14s, ticking). journald capped 1G + rate-limit. Both live, persist via drop-ins.
- 44/46 containers have mem_limit (generous backstop). 0 unhealthy / 0 restarting.
- ZERO reboots used. cmdline.txt untouched (was already correct — firmware-token false premise).
- OPEN: (1) loyalty-cards-app @ /home/deploy/deployments/LoyaltyCards — needs user decision (pipeline-managed; limit belongs in source repo). (2) commit compose edits (user must approve). (3) optional: a real reboot sometime to confirm clean boot + watchdog persistence (not required).

---

## Phase B — journald hardening

File: `/etc/systemd/journald.conf.d/10-hardening.conf`
```
[Journal]
SystemMaxUse=1G
RuntimeMaxUse=128M
RateLimitIntervalSec=30s
RateLimitBurst=5000
```
Rationale: journal had grown to 3.6 G. `SystemMaxUse=1G` bounds disk while keeping weeks of forensic history (this very investigation used 28-day-old logs). Rate limit kept near-default (5000/30s) to avoid dropping legit incident logs. Apply: `systemctl restart systemd-journald`. Verify: `journalctl --disk-usage`, `systemd-analyze cat-config systemd/journald.conf | tail`.

## Phase C — Watchdog (the "had to power-cycle" fix)

File: `/etc/systemd/system.conf.d/10-watchdog.conf`
```
[Manager]
RuntimeWatchdogSec=14s
RebootWatchdogSec=2min
```
BCM2835 hw watchdog max = **15 s** (verified via `wdctl`), so 14 s stays safely under. systemd (PID1) pings every ~7 s; if PID1 livelocks, hardware resets in ≤14 s → auto-reboot instead of manual power-cycle. `RebootWatchdogSec=2min` covers a hung shutdown. Apply live: `systemctl daemon-reexec`. Verify: `wdctl` shows Timeleft ticking; journal logs "Watchdog running with a hardware timeout of...". (`watchdog.service` external daemon stays inactive — no conflict.)

## Phase D — mem_limit tiers (generous backstop)

Per-container ceilings (sum intentionally exceeds 8 GB — these are caps, not reservations; protect against a single runaway). Syntax: `mem_limit:` under each service (Compose v2, honored by `docker compose up`). Match each project's existing file style.

| Tier | Limit | Containers (observed MiB) |
|------|-------|---------------------------|
| micro | 64m | autoheal-nzb, autoheal-mouse, autoheal-antivirus, duckdns, noip, port_updater |
| small | 128m | node-exporter, WireGuard-VPN, claude-mockups, claude-mockups-inbox, homelab-dashboard, wg-chores-sqliteweb, loyalty-cards(frontend) |
| std | 256m | adguardhome, telegraf, Dashy, mousehole, traefik, wg-chores-app, sbb-easyride-taxreport, portainer, cloudflared, samba, backdrop-carousel, digitec_web, digitec_pgweb, loyalty-sync, loyalty-cards-backend, gluetun_nzb, gluetun_mouse |
| medium | 512m | loyalty-cards-cloudbeaver, stonks, grafana, audiobookshelf, authentik-postgresql, qbittorrent_mouse, bitwarden, digitec_db |
| heavy | 1g | influxdb, prometheus, sabnzbd, authentik-server, authentik-worker |
| xheavy | 1536m / 2g | clamav=1536m, jenkins-jdk-21=2g |

### Per-project apply order (safe → sensitive)
Non-critical first; remote-access / DNS / VPN LAST.
1. Watchtower, DDNS(duckdns/noip/port_updater), Dashy, BackdropCarousel, Claude-Mockups, mouse(homelab-dashboard?)
2. monitoring: grafana(grafana/prometheus/influxdb/telegraf/node-exporter), Stonks, sbb-easyride-taxreport, LanguageTool
3. apps: audiobookshelf, bitwarden, LoyaltyCards(+Sync), nzb(gluetun/sabnzbd/autoheal), mouse(gluetun/qbittorrent/mousehole/autoheal), Jenkins, antivirus(clamav/autoheal), HashiCorpVault, samba(?), Portainer
4. **SENSITIVE LAST:** Authentik (SSO), Traefik (proxy), cloudflared (tunnel), adguard (DNS), WireguardVPN (VPN — may drop user's own access briefly)

For each project: read compose → add `mem_limit` per service → `cd <proj> && docker compose up -d` → verify `docker ps`/health + service reachable → tick below.

### Authoritative container -> compose file map (from docker labels)
Standard tree `/home/pi/Projects/Docker/<proj>/docker-compose.yaml`:
adguard[adguardhome], antivirus[autoheal-antivirus,clamav,virustotal], audiobookshelf[audiobookshelf],
Authentik[postgresql,server,worker], BackdropCarousel[backdrop-carousel], bitwarden[bitwarden],
Claude-Mockups[claude-mockups,answer-inbox], cloudflared[cloudflared], Dashy[dashy], DDNS[duckdns,noip],
grafana[prometheus,node-exporter,grafana,influxdb,telegraf], Jenkins[jenkins], LoyaltyCards[loyalty-cards],
LoyaltyCards-Sync[loyalty-sync], mouse[samba,autoheal-mouse,gluetun,qbittorrent,mousehole,port-updater],
nzb[autoheal-nzb,gluetun,sabnzbd], Portainer[portainer], sbb-easyride-taxreport[sbb_easyride_taxreport],
Stonks[stonks], Traefik[traefik], WireguardVPN[wg-easy], HashiCorpVault[vault — NOT running].

OUTLIERS (outside the standard tree):
- landingpage[homelab-dashboard] -> /home/pi/landingpage/docker-compose.yaml  (user-owned; INCLUDE)
- digitec-price-tracker[web,db,pgweb] -> /home/pi/Documents/development/Digitec-PriceTracker/docker-compose.yml (user dev; INCLUDE)
- wg-chores[wg-chores,sqlite-web] -> /home/pi/Documents/development/WG-Chores/docker-compose.yml (user dev; INCLUDE)
- loyalty-cards-app[loyaltycardsbackend,cloudbeaver] -> /home/deploy/deployments/LoyaltyCards/docker-compose.yaml
  ** DEFER + FLAG: production, owned by `deploy` user, pipeline-managed. Limit belongs in SOURCE repo, not deployed file. Ask user. **

### Phase D checklist (tick per project after verify)
- [x] DDNS(64m/64m)  - [x] Dashy(256m)  - [x] BackdropCarousel(256m, fixed stale proj)  - [x] Claude-Mockups(128/128)  - [x] landingpage(128m)
- [x] grafana(prom1g,node128m,graf512m,influx1g,tele256m)  - [x] Stonks(512m)  - [x] sbb-easyride-taxreport(512m)  - [x] digitec-price-tracker(web256,db512,pgweb256)  - [x] wg-chores(app512,sqliteweb128)
- [x] audiobookshelf(512m)  - [x] bitwarden(512m)  - [x] LoyaltyCards(128m)  - [x] LoyaltyCards-Sync(256m)
- [x] nzb(autoheal64,gluetun256,sab1g)  - [x] mouse(samba256,autoheal64,gluetun256,qbit512,mousehole256,portupd64)  - [x] Jenkins(2g)  - [x] antivirus(autoheal64,clamav2g[bumped from 1536m: clamd DB footprint],vt256)  - [x] HashiCorpVault(512m; vault EXITED-edited only)  - [x] Portainer(256m)
- NOTE: stale COMPOSE_PROJECT_NAME drift possible elsewhere — verify step catches it (conflict→`docker rm -f <name>`+`up -d`).
- [x] Authentik(pg512,server1g,worker1g)  - [x] Traefik(256m, HTTP301/HTTPS ok)  - [x] cloudflared(256m, tunnel reconnected 3 conns)  - [x] adguard(256m, DNS verified)  - [x] WireguardVPN(128m, 51820/udp + wg0 up)
- [ ] (DEFERRED) loyalty-cards-app @ /home/deploy — needs user decision (pipeline-managed)
- note: Watchtower/LanguageTool/Deprecated/infrastructure-OLD — not running; skip or limit-on-touch.

---

## STATUS POINTER  (update before each command)

**CURRENT:** Executing Phase B (journald) + Phase C (watchdog) — writing drop-ins, applying live. NEXT: verify both, then Phase D.

## COMMAND LOG  (append before running; note result after)

- Phase A: runbook written (done). Commit deferred to Phase E (batch).
- Phase B: write `/etc/systemd/journald.conf.d/10-hardening.conf` (sudo tee) → `sudo systemctl restart systemd-journald` → verify.
- Phase C: write `/etc/systemd/system.conf.d/10-watchdog.conf` (sudo tee) → `sudo systemctl daemon-reexec` → verify `wdctl` Timeleft ticking.
