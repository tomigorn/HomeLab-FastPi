# Docker `userns-remap` migration plan & rollback runbook

Goal: shrink container-escape blast radius so a breakout does **not** inherit `pi` (uid 1000 / sudo).
With daemon-wide `userns-remap`, in-container uid 0..N map to unprivileged host subuids, so a container
root that escapes lands on a harmless high uid with no host rights.

Status: **PREPARED, NOT CUT OVER.** `daemon.json` not written, dockerd not restarted. Flip is a
machine.md yes-first, owner-present action (restarts every container incl. edge + VPN + LAN DNS).

## Remap identity (already provisioned, non-disruptive)

| Item | Value |
|---|---|
| Remap user | `dockremap` (system, nologin) — created |
| `/etc/subuid`, `/etc/subgid` | `dockremap:296608:65536` — added (next free after `pi/deploy/mouse`) |
| Base subuid (in-container uid 0) | host **296608** |
| In-container uid X maps to host | **296608 + X** |

Common mappings: `0`→296608, `1000`→297608, gid `1100`→297708, `1101`→297709, `1102`→297710, `65532`→362140.

Snapshot of pre-state: `_global/docs/userns-remap-snapshot/` (docker info, subuid/subgid before+after).
There is **no** `/etc/docker/daemon.json` today — cutover must *create* it.

## The two dominant costs (read before planning a window)

1. **Data-root relocation.** With remap on, dockerd uses a *new* root `/var/lib/docker/296608.296608/`.
   Every existing **named volume, image and container under `/var/lib/docker/` becomes invisible.**
   All images must be re-pulled and **every named volume migrated** (copy + uid-shift). Stateful volumes
   affected: `authentik_database-pg18`, `monitoring__grafana_{influxdb,prometheus,grafana,alertmanager}_data`,
   `jenkins_home`, `vault_vault-data`, `crowdsec_crowdsec_{config,data}`, `loyalty*`, `digitec*`,
   `adguard_adguardhome-data`, `antivirus_clamav-db`, `mouse_*`, `nzb_gluetun-data`, `wg-chores_wgchores-data`.
2. **Shared `/mnt` ownership conflict.** `/mnt/seagate-red` + `/mnt/seagate-black` are owned `1101:1100`
   and written by **Samba (host-net, uid 1101)** *and* read/written by **qbittorrent/sabnzbd (gluetun
   netns, would be remapped to 297709)** and ABS. One directory cannot satisfy both a host uid and a
   remapped uid. **Do not recursively chown terabytes of media** — exempt the whole media path instead
   (see exception list). Chowning `/mnt` recursively is explicitly rejected as the approach.

Consequence: this is a **big-bang, multi-hour, full-outage change**, not a seconds-long restart. Docker
only supports *opting out* per container (`userns_mode: host`); you cannot remap a subset — the default
flips for all at once.

## Bind-mount / ownership table

Remapped rw dirs need `chown` to `base+uid`. `:ro` config at 644/755 owned 1000 is readable by any
remapped uid (other-readable) — **no chown**. `:ro` secrets at 600 need chown. Host-net/exempt stacks
keep host ownership (no chown). Named-volume data is migrated separately (see cost #1).

| Stack | Host path | Now (uid:gid mode) | In-ctr uid | Action |
|---|---|---|---|---|
| Authentik | `./data` | 1000:1000 775 | root/1000 | chown → 296608/297608; `custom-templates` is 0:0 → 296608; **DB in named vol (migrate)**. EDGE-CRIT |
| Traefik | `./traefik/letsencrypt`,`/logs` | 1000:1000 755 | root | chown → 296608. EDGE-CRIT |
| Traefik | `./traefik/secrets` (600 files) | 1000:1000 | root | chown → 296608 |
| Traefik | `./traefik/{traefik.yml,dynamic,plugins-local}` | 1000:1000 ro | — | none (ro, readable) |
| CrowdSec | `config/acquis.yaml`, traefik logs | 1000:1000 644 ro | root | none (ro); data in named vols (migrate) |
| bitwarden | `./data` | 1000:1000 755 | root | chown → 296608 |
| Stonks | `./data` | **0:0** 755 | root | chown → 296608 |
| Claude-Mockups | `./answers` (rw) | 1000:1000 755 | 1000 | chown → 297608; www/assets/inbox ro → none |
| HashiCorpVault | `vault_vault-data` (vol) | — | ~100 | migrate vol; cap IPC_LOCK ok under userns |
| grafana | `grafana/alertmanager/secrets` (600) | 1000:1000 | — | chown → owner uid; most configs ro → none |
| grafana | prom/influx/grafana/alertmanager data | named vols | 1000/various | migrate vols |
| grafana | node-exporter `/`,`/proc`,`/sys`,textfile | host ro | root | none (ro) |
| LanguageTool | `shared`,`config`,`logback` | 1000:1000 ro | — | none (ro) |
| BackdropCarousel | `./photos` | 1000:1000 ro | — | none (ro) |
| Cup | `cup.json` | 1000:1000 644 ro | — | none (ro) |
| M4b-Merge-Dashboard | `www`,`${RUNS_DIR}` | 1000:1000 ro | 1000 | none (ro) |
| M4b-Auto-Merge | `secrets/*` (600), writes `/mnt` library+quarantine | 1000:1000 | 1000 | **EXEMPT** (writes shared /mnt) |
| Avatar-Picker | `./secrets/{authentik_token,picker_secret}` | 1000:1000 **600** | 1000 | chown secrets → 297608 (keep 600) |
| Beefy/Tower-Waker | `./secrets/*` (600), `./app` | 1000:1000 | 1000 | **EXEMPT** (host-net) → stays host 1000, secrets readable |
| Home-Assistant | `./config`, serial device, `/etc/localtime` | 1000:1000 | root | **EXEMPT** (host-net + device) |
| adguard | `./conf` | 1000:1000 755 | root | **EXEMPT** (host-net, LAN DNS) + data vol migrate |
| DDNS | `./config`,`./noip_config` | 1000:1000 / 0:0 | root | **EXEMPT** (host-net ×2) |
| WireguardVPN | `./wg-easy-v15`, `/lib/modules` | 1000:1000 | root | **EXEMPT** (SYS_MODULE kernel load not allowed in userns). VPN-CRIT |
| nzb | gluetun+sabnzbd, `/mnt/seagate-red/sabnzbd`, PUID 1101 | 1101:1100 | 1101 | **EXEMPT** (shared /mnt, host uid 1101) |
| mouse | samba(host-net 1101/1102), gluetun+qbit `/mnt/seagate-red/qbittorrent` | 1101:1100 | 1101 | **EXEMPT** (host-net + shared /mnt) |
| audiobookshelf | `/mnt/seagate-black/library/{audiobooks,podcasts}` | 1101:1100 | 1000 | **EXEMPT** (reads shared /mnt library) |
| Jenkins | docker.sock, `/usr/bin/docker`, `jenkins_home` | privileged+root | root | **EXEMPT** (privileged incompatible with userns) |
| Docker-Socket-Proxy | `/var/run/docker.sock` | root:docker 660 | haproxy | **EXEMPT** (real docker.sock unreadable by remapped uid) |
| Portainer | `/var/run/docker.sock:ro` | root:docker 660 | root | **EXEMPT** (real docker.sock) |
| Watchtower | docker.sock | root:docker 660 | root | **EXEMPT** (docker.sock) |
| cloudflared | `tunnel_token.secret` 644 | 1000:1000 644 | 65532 | none (644 other-readable; maps 362140) |

Bind-mount count enumerated: **~60 mount lines across 30 compose files.** Of these, the overwhelming
majority are `:ro` config/scripts that need no change; the real work is (a) chown of a handful of rw
local dirs + 600 secrets, (b) named-volume migration, (c) correctly exempting the ~15 stacks below.

## Exception list — `userns_mode: host` required (opt OUT of remap)

| # | Stack/container | Reason |
|---|---|---|
| 1 | adguard | host-net; **LAN DNS** — must stay up |
| 2 | Home-Assistant | host-net + `/dev/serial` Zigbee dongle |
| 3 | Beefy-Waker | host-net (WOL broadcast) |
| 4 | Tower-Waker | host-net (WOL broadcast) |
| 5 | DDNS (cloudflare + noip) | host-net ×2 |
| 6 | mouse/samba | host-net, uid 1101/1102 on `/mnt` |
| 7 | WireguardVPN/wg-easy | SYS_MODULE — loading kernel modules is not permitted from a user namespace |
| 8 | Jenkins | `privileged: true` — incompatible with userns unless host |
| 9 | Docker-Socket-Proxy | mounts real `docker.sock` (root:docker 660) |
| 10 | Portainer | mounts real `docker.sock` |
| 11 | Watchtower | mounts real `docker.sock` |
| 12 | nzb (gluetun+sabnzbd) | shares `/mnt/seagate-red` with host-uid Samba |
| 13 | mouse (gluetun+qbit+mousehole+port-updater) | shares `/mnt/seagate-red` with Samba |
| 14 | audiobookshelf | reads `/mnt/seagate-black/library` (host uid 1101) |
| 15 | M4b-Auto-Merge | writes `/mnt` library + quarantine |

Per-container secret handling to apply during cutover (remapped stacks only):
- **Avatar-Picker** `secrets/{authentik_token,picker_secret}` (600, uid 1000): `chown 297608:297608`, keep 600.
- **Traefik** `traefik/secrets/*` and **grafana** `alertmanager/secrets/*` (600): chown to the stack's remapped owner.
- cloudflared token already 644 (intentionally) → readable by remapped 362140, leave as-is.

## Recommended strategy: phased exemption (lowest blast radius)

Docker cannot remap a subset, but you can flip the default **once** while exempting everything risky,
so only low-value stateless stacks actually get remapped first; then peel back exemptions over later
supervised sessions, migrating one stack's volume at a time.

- **Phase 1 (this cutover):** flip default remap; apply `userns_mode: host` to **all 15 exceptions**
  *and* to the edge/stateful set (Traefik, Authentik, CrowdSec, grafana, Vault) too. Only the stateless
  app stacks (Stonks, Claude-Mockups, BackdropCarousel, LanguageTool, Cup, sbb-easyride) remap. Proves
  the mechanism with the homelab staying up.
- **Phase 2+ (later supervised sessions):** remove `userns_mode: host` from one edge/stateful stack at
  a time, migrate its named volume, chown its bind dirs, recreate, verify. Smaller windows each.

The big-bang alternative (remap everything except the 15 exceptions in one go) is documented below but is
higher risk.

## CUTOVER RUNBOOK (big-bang — owner present only)

Estimated **full outage 1–3 h**, dominated by image re-pull + named-volume migration (Postgres/InfluxDB).
**Prerequisite: a fresh, verified backup of `/var/lib/docker/volumes` and all `./data` dirs.**

0. Owner present; confirm usage-window headroom. Announce outage. Have a second SSH session open.
1. `docker ps -a --format '{{.Names}}' > /tmp/ctr.before` and record `docker images` digests.
2. Stop everything: in each stack dir `docker compose down` (edge/VPN/DNS LAST). Confirm `docker ps` empty.
3. Write `/etc/docker/daemon.json`:
   ```json
   { "userns-remap": "dockremap" }
   ```
   (merge, don't clobber, if one appears later.)
4. **Migrate named volumes** to the new root. For each volume dir under `/var/lib/docker/volumes/<v>/_data`,
   copy to `/var/lib/docker/296608.296608/volumes/<v>/_data` preserving perms, then
   `chown -R` shifting every uid/gid by **+296608** (e.g. `find ... -printf` + offset, or
   `chown -R --from=OLD NEW` per known uid). Verify sizes match. (Exempted stacks' volumes: copy, then
   shift by +296608 as well, because dockerd itself now lives under the remapped root — but their
   *containers* run host-mapped, so files they create use host uids; set initial ownership to the host
   uid the container runs as.) **This step is the long pole; stage it before the window if possible.**
5. Apply `userns_mode: host` to the 15 exception stacks in their compose files (and to edge/stateful if
   doing the phased variant).
6. chown remapped bind dirs: `Authentik/data`→297608 (+custom-templates→296608), `Traefik/{letsencrypt,logs,secrets}`→296608,
   `bitwarden/data`→296608, `Stonks/data`→296608, `Claude-Mockups/answers`→297608,
   `Avatar-Picker/secrets`→297608, grafana `alertmanager/secrets`→owner.
7. `sudo systemctl restart docker`. **Immediately** `docker info | grep userns` → expect
   `userns: default` / remap active; `ls /var/lib/docker/296608.296608`.
8. Bring stacks UP in dependency order, verifying at each gate:
   - **Gate A — Docker socket chain:** Docker-Socket-Proxy, Portainer. `docker ps` healthy.
   - **Gate B — edge:** cloudflared, Traefik, CrowdSec, Authentik. Then run **Verification checklist**.
   - **Gate C — LAN DNS + VPN:** adguard (`dig @127.0.0.1 sso.holy-grail.ch`), WireguardVPN (`wg show`).
   - **Gate D — the rest:** media (nzb, mouse, audiobookshelf), grafana, HA, wakers, apps.
9. `docker ps` vs `/tmp/ctr.before` — every container back and healthy. Check `docker logs traefik`
   (fails CLOSED — must be clean). Done.

## Verification checklist (run at Gate B/C and at end)

- Edge routes: `curl -so /dev/null -w '%{http_code}\n' https://sso.holy-grail.ch/` → **200/302**;
  a protected app (e.g. grafana) unauthenticated → **302 to Authentik**; a bogus host → **404**.
- Traefik log clean (no plugin/route load errors) — it fails closed; a failure 404s every public route.
- `dig @192.168.1.2 sso.holy-grail.ch +short` resolves (AdGuard wildcard working).
- `sudo wg show` (or wg-easy UI) lists expected peers; a VPN client re-handshakes.
- SSO login challenge: open an app from a clean browser → Authentik login → MFA → lands on app.
- CrowdSec: `docker exec crowdsec cscli metrics` returns; decisions list loads.
- Each remapped container's files: `docker exec <c> id` shows expected in-ctr uid; `ls -n` on a data
  mount shows host owner = base+uid.

## ROLLBACK RUNBOOK

Fast and reliable because the pre-remap data-root is left untouched by the migration (we *copied*, not moved).

1. `docker compose down` every stack (or `systemctl stop docker`).
2. Remove/empty `/etc/docker/daemon.json` (delete the file — it did not exist pre-migration) OR
   restore the backed-up original if one is reintroduced later.
3. Revert the `userns_mode: host` additions in the 15 compose files (`git checkout` those files).
4. Revert bind-dir ownership: `chown -R 1000:1000` the dirs chowned in Cutover step 6
   (`Stonks/data` back to 0:0, `Authentik/custom-templates` back to 0:0).
5. `sudo systemctl restart docker`. `docker info | grep userns` → **should be empty** (remap off).
   dockerd reads the original `/var/lib/docker/` root → all original volumes/images/containers reappear.
6. Bring stacks up in the Gate A→D order. Run the full Verification checklist.
7. The new-root copy `/var/lib/docker/296608.296608/` can be left in place or removed once stable.

Panic path (remap on, won't start, owner gone): `rm /etc/docker/daemon.json && systemctl restart docker`
returns to the untouched original root — this is why the migration **copies** volumes and never deletes the
original root.

## Why prepare-but-don't-cut-over was correct

Flipping the default restarts **every** container, including Traefik/Authentik/CrowdSec (public edge, fails
closed), AdGuard (LAN DNS for the whole house) and WireGuard (remote access). The data-root relocation forces
a full image re-pull and named-volume migration of live Postgres/InfluxDB, so a mistake (missed volume, wrong
chown offset, Traefik plugin load failure) downs the entire homelab — and an **unattended** failed rollback
would leave it down until morning with no remote access (VPN itself would be down). The outage is hours, not
seconds. All of that makes it a machine.md yes-first, owner-present action. The safe, non-disruptive 90% —
remap user, subuid/subgid ranges, full ownership/exception analysis, and a tested rollback — is done here, so
the cutover is a ready, supervised one-shot.
