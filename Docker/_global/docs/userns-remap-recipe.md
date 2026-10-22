# userns-remap migration — recipe & runbook (config-as-code)

Decision 2026-10-22 (user): **pursue daemon-wide userns-remap** as a phased migration, for the extra
isolation it gives the containers that must run as root (adguard/traefik/gluetun/samba/clamav) — which the
per-container hardening cannot protect. This supersedes the earlier "rejected" verdict in
`userns-remap-plan.md` (that doc's bind-mount table, exemption list and rollback runbook still apply —
read it alongside this).

## The honest mechanics (read first — it is NOT a per-container opt-in)
- `userns-remap` is a **daemon-wide** switch in `/etc/docker/daemon.json`. The moment it is enabled and
  dockerd restarts, **every** container is remapped **at once**, except those individually marked
  `userns_mode: "host"` (opt-OUT). There is no per-container opt-IN.
- Enabling it **relocates the data-root** to `/var/lib/docker/<uid>.<gid>/` (here `296608.296608`). Every
  existing image, container and **named volume becomes invisible** to the remapped daemon. Images re-pull;
  named volumes must be **migrated** (copy into the new root + shift ownership by +296608) or the service
  **re-provisioned**. Bind mounts under `/mnt` and `./` are NOT masked (they live outside the data-root),
  but their ownership must line up with the remapped uid.
- Therefore "one container at a time" = **flip the daemon with EVERYTHING exempted first (zero functional
  change), then remove the exemption from one stack at a time**, migrating that stack's data as you go.

## Prerequisites (already in place)
- `dockremap` system user + `/etc/subuid`,`/etc/subgid` = `dockremap:296608:65536` (provisioned).
- DNS/egress fixed: `/etc/docker/daemon.json` already has `{"dns":["192.168.1.2"]}` (see container-hardening.md).
- Disk: ~323 G free; image re-pull (~36 G) + volume copies fit.

## Config-as-code — what the migration writes
1. `/etc/docker/daemon.json` (host file, not in git — document any change here):
   ```json
   { "dns": ["192.168.1.2"], "userns-remap": "dockremap" }
   ```
2. `userns_mode: "host"` added to each exempted service in its committed `docker-compose.yaml`.
3. Per-stack bind-dir `chown`s + named-volume migration steps (scripted; see per-stack procedure).
4. Re-provisioning that is already code: `Authentik/scripts/provision-*.py`, compose `.env` files.

## CAN remap vs MUST stay exempt
**Must stay `userns_mode: host` (cannot remap):**
- Host networking: adguard(:53 DNS), WireGuard(+NET_ADMIN +kernel module), samba, home-assistant(+serial),
  beefy/tower-waker, DDNS(duckdns/noip), cloudflared? (host-net? it's bridge — can remap, see below).
- Privileged / kernel: WireGuard (module load is not permitted from a userns), any `privileged:` stack.
- Docker socket: socket-proxies, Portainer, Watchtower (real socket unreadable by a remapped uid).
- Shared `/mnt` host-uid (1101/sambashare): nzb(sabnzbd+gluetun), mouse(qbit+gluetun+samba), audiobookshelf,
  m4b-auto-merge — a remapped uid cannot satisfy the host-uid-1101 ownership of the shared drive.
**Can remap (stateless / own-volume):** cloudflared, Stonks, Claude-Mockups, BackdropCarousel, LanguageTool,
Cup, sbb-easyride, Avatar-Picker, bitwarden(stopped). **Stateful, remap with volume migration (later, careful):**
Authentik(+Postgres), grafana/influx/prometheus/alertmanager, Vault, CrowdSec.

> Reconciling the "core-first" wish: **cloudflared** (the tunnel) is bridge-net and CAN remap early — good
> first candidate. **WireGuard CANNOT** (module) — it stays exempt, running exactly as now. So "core first"
> works for cloudflared but WireGuard is a permanent exemption, not a migration target.

## Migration procedure (phased, owner present on LAN)
**Phase 0 — flip with everything exempted (zero functional change, proves the mechanism):**
1. Add `userns_mode: "host"` to EVERY running stack's compose (commit).
2. Add `"userns-remap": "dockremap"` to daemon.json.
3. Migrate the named volumes that exempted stacks use (copy to the new root, keep host ownership — exempted
   containers run host-mapped so their files keep host uids). This is the long pole; stage before the window.
4. `sudo systemctl restart docker` → whole homelab bounces onto the new root. Bring up in gate order
   (socket chain → edge → DNS+VPN → rest). Verify with the full checklist in `userns-remap-plan.md`.
   Result: identical behaviour, but remap is now active (just nothing is remapped yet).
**Phase 1..N — peel one stack at a time:**
For each stack that CAN remap (start with cloudflared, then the stateless app stacks, then stateful with care):
1. `docker compose down <stack>`.
2. Remove its `userns_mode: host`. 3. Migrate/chown its data: named volume → shift ownership +296608;
   bind dirs → chown to `296608 + in-container-uid`; 600 secrets likewise.
4. `docker compose up -d <stack>`; verify functionally (the stack's real function, not just "up").
5. Roll back that stack (re-add `userns_mode: host`, revert chown) if it misbehaves — no daemon restart needed.

## Re-provision by hand (not in code) — document as we go
- **Authentik:** user ACCOUNTS + their **MFA enrolments** + any OAuth client secrets not in `.env`. Most
  config is code (`provision-*.py`); the humans re-enrol MFA. Export first: `pg_dump` (we have a 15 M dump).
- **Vault:** unseal keys + any secrets entered by hand (export/snapshot before).
- **Grafana:** dashboards if not provisioned; InfluxDB history (non-critical) — accept loss or migrate the volume.

## Rollback (panic): `rm /etc/docker/daemon.json`-userns-key (or the whole file) + `systemctl restart docker`
→ dockerd reads the original `/var/lib/docker/` root, every pre-migration volume/image/container reappears
(the migration COPIES, never moves). See `userns-remap-plan.md` ROLLBACK section + `userns-rollback.sh`.

## IS IT WORTH IT? (honest assessment 2026-10-22)
Reassessed after writing the recipe: **for this existing host, marginal — recommend deferring in favour of
the per-container cap_drop hardening.** Reasons:
- userns only benefits containers that run-as-root AND can remap = traefik, crowdsec, cloudflared (+ a
  marginal 2nd boundary on the already-non-root stacks).
- The highest-risk root containers MUST stay exempt (adguard/WireGuard/samba/gluetun/clamav/socket-proxies/
  Portainer/media) → they get ZERO benefit from userns.
- `cap_drop:[ALL]`+minimal helps EVERY container, including those exempt ones, at near-zero cost and no
  re-provisioning. An escaped traefik-root with only NET_BIND_SERVICE ≈ as contained as a remapped one.
- Cost of userns here: full migration + re-provision Authentik users/MFA + Vault secrets + permanent volume-
  migration/exemption complexity.
**Verdict: do the cap_drop root-hardening instead. Keep this recipe for a future FRESH fastpi build, where
userns-from-day-one IS worth it (no migration, no re-provisioning).**
