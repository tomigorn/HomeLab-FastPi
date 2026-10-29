# Tower-Waker

Wakes **tower** (`192.168.1.101`, the Unraid NAS) on demand, so it can power
itself off when idle and come back on first access. Runs on **fastpi**, the
always-on Traefik edge, on host network port **`:9002`** (`:9001` is
[Beefy-Waker](../Beefy-Waker/README.md), which this mirrors — read that README
for the endpoints, the gate, the wake page and the deploy steps; everything
below is only what differs for tower).

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
awake** (it checks the waker's `/status`, never sends a WoL), with 30
hard-linked daily snapshots and `latest` pointing at the newest. The tree is
mode 700 and outside git (it contains `shadow`, SSH keys, WireGuard keys).
Logs: `journalctl --user -u tower-flash-backup.service`.
Restore: new stick via the USB creator, copy a snapshot onto its `/config`,
boot, Tools → Registration → Replace Key if the GUID changed.

## Operations

- Listen backlog 64 (`request_queue_size`), same as Beefy-Waker.
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

**Rebuild** (`tower-waker:local`, FROM `python:3.13-alpine`): `docker compose up -d --build --pull` when Cup shows an update for the base or the security scan lists a fixable base CVE, otherwise monthly. The image has no pip (removed in the `Dockerfile`).
