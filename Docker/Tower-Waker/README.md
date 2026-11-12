# Tower-Waker

Wakes **tower** (`192.168.1.101`, the Unraid NAS) on demand, so it can power
itself off when idle and come back on first access. Runs on **fastpi**, the
always-on Traefik edge, on host network port **`:9002`** (`:9001` is
[Beefy-Waker](../Beefy-Waker/README.md), which this mirrors — read that README
for the endpoints, the gate, the wake page and the deploy steps; everything
below is only what differs for tower).

Since v2.0.0 the waker is Rust (`rust/`, static binary in a `scratch` image, uid 65006); the old Python app stays in `app/` (`app/Dockerfile.python`) until the owner removes it. Behaviour, pages, log lines and env vars are unchanged; the black-box suite proves it against both.

| Path | What |
|---|---|
| `rust/` | the waker (`src/main.rs` routes + Nextcloud policy, `web.rs` HTTP layer, `wol.rs` magic packet; `web.rs`/`wol.rs` are identical copies of Beefy-Waker's) |
| `tests/blackbox/` | black-box suite (32 tests, fakes for tower and the WoL broadcast, network-less `ctest.sh` container): `tests/blackbox/run.sh old` (Python) / `run.sh new` (binary from `tower-waker:local`) |
| `app/` | legacy Python app + `VERSION` (mounted at `/app/VERSION`, shown in the pages) |

## How tower sleeps and wakes (the beefy logic, Unraid flavour)

| Part | beefy | tower |
|---|---|---|
| Idle → power off | systemd watcher, 15 min | User Scripts cron `*/5`, **30 min** idle (`idle-shutdown` on the flash) |
| Busy signals | SSH, VS Code, inbound service conns, CPU/net/disk | SSH/SMB/NFS conns, Nextcloud requests + in-flight uploads, backup jobs, parity/scrub/SMART jobs, disk writes |
| Pause auto-off | `touch /run/beefy-keep-awake` | `touch /boot/config/no-autoshutdown` (survives reboots) |
| WoL armed | netplan `wakeonlan: true` | NIC `Wake-on: g`; the script re-arms it right before `powerdown` |
| Wake on request | `beefy-wake` → `:9001` | `tower-wake` → `:9002`, chained behind a rate limit (Nextcloud is public) |
| Readiness probe | `beefy:22` | `tower:8080` (Nextcloud) — sshd answers ~15 s before the array is up |
| `ssh host` wakes it | yes | yes (`Match host tower` in `~/.ssh/config`) |

30 min, not 15, is deliberate: `disk1` is a WD60EFAX **SMR** drive that
reorganises its shingled zones after writes, and the script gives it a quiet
window before power is cut.

**Unraid gotcha:** User Scripts only installs its cron entries once the array
has started. If the array cannot start (missing/expired licence, bad disk),
the idle-shutdown never runs and tower stays on at full power until someone
powers it off.

## Cold boot timing (measured 2026-10-14)

Method: `powerdown` over a direct-IP ssh (bypasses the wake hook), 60 s in S5,
one `wakeonlan 60:be:b4:17:0d:e0`, then poll from fastpi. Two runs, ~1 s apart.
Hardware: Celeron N5105 board (`GFJSL-V1.1-R208` BIOS), 16 GB, flash on USB,
1 HDD + 2 SATA SSDs. BIOS at its defaults, no fast-boot tuning done.

| Stage (from the magic packet) | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| First ping reply | 61.0 s | 62.8 s | 75.3 s |
| ssh port 22 open | 62.9 s | 63.9 s | 76.8 s |
| Unraid webGUI `:80` open | 77.9 s | 79.0 s | 91.3 s |
| Array mounted / Nextcloud `:8080` | — | — | **107.5 s** (run 3, licence restored) |

Run 3 (same method, after the licence was fixed): ping 75.3 s, ssh 76.8 s,
webGUI 91.3 s, Nextcloud 107.5 s — ~13 s slower to ssh than runs 1–2 because
that boot had a ~31 s POST instead of ~17 s (first power-on after a `reboot`
rather than a `powerdown`); kernel→sshd was identical (~46 s).

Breakdown from the kernel's own uptime when ssh opened: **~16.6 s of
firmware/POST** before the kernel, then **~46 s** from kernel to sshd (Unraid
unpacks its whole root filesystem from the USB flash into RAM on every boot,
which is where most of that goes). `powerdown` → machine silent: ~41 s.

So WoL → fully usable (array mounted, Nextcloud answering) is **~105–110 s**,
consistent with the Aug 2026 measurement of ~102 s; `WAKE_COUNTDOWN=120` is
sized right.

Where the time goes and what could change it:
- Firmware 16.6 s is already short (beefy's board takes 27–32 s). Not worth
  BIOS experiments.
- The ~46 s kernel→sshd is Unraid's USB-flash boot (bzroot extraction + plugin
  install). A faster USB stick helps a little; nothing in the BIOS does.
- Array start (+20–25 s) is the HDD spin-up plus pool mount; inherent.

## Config (`.env`)

Same variables as Beefy-Waker, prefixed `TARGET_*`. The two that differ and
why are commented in `.env.example`: `TARGET_PROBE_PORT=8080` and
`WAKE_COUNTDOWN=120`. `/history` does not work for tower (no journalctl on
Unraid).

## Flash backup (`scripts/tower-flash-backup.sh`)

tower's whole identity lives on its USB flash (`/boot/config`: licence key,
array/pool config, shares, users, secrets, plugins). A systemd **user timer on
fastpi** (`tower-flash-backup.timer`, hourly, units in
`~/.config/systemd/user/`) runs the script, which copies `/boot/config` to
`~/backups/tower-flash/<date>/` once a day — **only when tower is already
awake** (a direct `ssh true` to the IP with `~/.ssh/tower`, never a WoL; the waker's
`/status` is not used, its probe is Nextcloud), with 30 hard-linked daily
snapshots (real directories) and `latest` pointing at the newest. On success it
writes `tower_flash_backup_last_success_timestamp_seconds` to the node-exporter
textfile dir; alert `TowerFlashBackupStale` fires after 8 days without one.
Test (offline, fake ssh/rsync): `bash tests/test-flash-backup.sh`. The tree is
mode 700 and outside git (it contains `shadow`, SSH keys, WireGuard keys).
Logs: `journalctl --user -u tower-flash-backup.service`.
Restore: new stick via the USB creator, copy a snapshot onto its `/config`,
boot, Tools → Registration → Replace Key if the GUID changed.

## Operations

- At most 512 open connections, 10 s to send the request headers; SIGTERM stops it at once.
- Healthcheck: `/tower-waker --health` (GET `/status` on the listen address).
- WoL target (`TARGET_BROADCAST`) must be an IPv4 address (no DNS lookups).
- `POST /wake` and `/nc/wake` need header `X-Wake: 1`, and a browser `Origin` must be this host, else 403 (CSRF guard, same as Beefy-Waker). ssh hook: `Match host tower exec "curl -fsS -m 5 -X POST -H X-Wake:1 http://192.168.1.2:9002/wake"`.
- Out-of-band wake if this container is down: `wakeonlan 60:be:b4:17:0d:e0` on fastpi.
- **Timing/checking trap:** every `ssh tower` fires `/wake`, and because the
  probe is Nextcloud, the waker then resends magic packets every 20 s for 5 min
  whenever Nextcloud is not answering — which re-wakes tower mid-shutdown. To
  reach tower without waking it: `ssh -i ~/.ssh/tower -o IdentitiesOnly=yes root@192.168.1.101`.
  To check whether it is up without waking it: `curl http://192.168.1.2:9002/status`.
- **Scanner traffic must never reach the gate.** 2026-10-16 the TowerWakeLoop alert
  fired: 802 requests/24 h on `cloud.holy-grail.ch`, nearly all internet scanners
  (no User-Agent, `/.env`, `/.git/HEAD`, `wp-login`…), and every new scanner IP woke
  tower. `Traefik/.../nextcloud.yml` now has two higher-priority routers that answer
  403 before the `tower-wake` middleware: one for requests without a User-Agent, one
  for well-known scanner paths. Any other public host behind a wake gate needs the
  same (or Authentik in front, as Jellyfin has).
- Licence: Unraid refuses to start the array without a valid key on the flash
  (`/boot/config/*.key`); emhttpd logs `cmdStart: no registration key`. Since
  2026-10-14 tower runs a perpetual **Starter** key (`Starter.key`; OS updates
  until 2027-10-14). Keep exactly one `.key` file in `/boot/config/`.

**Rebuild** (`tower-waker:local`, build stage FROM `rust:1-alpine@sha256:…`, pinned by digest, A-30; `cargo test` runs in the build): `flock ~/.cache/claude-work/rust-build.lock ../_global/scripts/update-project.sh . build` (one Rust build at a time on fastpi). Automatic: weekly `rebuild-local` (`Server/4-Security-Monitoring/auto-updates.md` "Local builds") moves the pin, rebuilds, runs the black-box suite on the new image and rolls back on failure; by hand: `python3 ../_global/scripts/rebuild_local.py Tower-Waker`.

**Rollback to Python:** `docker tag tower-waker:pre-rust-2026-11-09 tower-waker:local`, restore `docker-compose.yaml` from git (`git show <commit before the Rust cutover>:Docker/Tower-Waker/docker-compose.yaml`), `docker compose up -d --force-recreate`.
