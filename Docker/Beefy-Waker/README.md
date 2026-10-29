# Beefy-Waker

Wakes **beefy** (`192.168.1.102`) on demand when a request arrives for any
beefy-hosted service, so beefy can sleep (S5 + WoL) to save power and come back
automatically on first access. Runs on **fastpi**, the always-on Traefik edge.

Part of the [beefy migration](https://github.com/tomigorn/HomeLab-BeefyServer)
wake-on-demand phase. The off/on mechanism (`ssh beefy-poweroff` /
`wakeonlan`) already exists; this is the **wake** half. beefy decides when to
*sleep* itself (see `Server/8-Idle-Watcher.md` in the beefy repo).

beefy can be woken **two ways**, both served by the one tiny `app/waker.py`
(host network, `:9001`):

1. **Automatically** — Traefik's `forwardAuth` gate (`/gate`) fires the WoL when a
   request arrives for a beefy service that's asleep.
2. **Manually** — open the **LAN wake page** (`/`) in a browser to wake beefy on
   demand, with a countdown and live status.

## 1. Automatic gate (`/gate`)

Traefik cannot run a script as middleware — a middleware is only a built-in, a
Go plugin, or **`forwardAuth`** (Traefik calls an HTTP endpoint and acts on the
status code). So it's a native `forwardAuth` middleware pointing at our gate:

```
request → Traefik router (a beefy host)
            → forwardAuth: GET http://192.168.1.2:9001/gate
                 ├─ beefy reachable?  TCP-probe 192.168.1.102:22
                 │     yes → 200  → Traefik proxies straight to beefy
                 │     no  → send WoL magic packet to 192.168.1.255:9,
                 │           return 503 + auto-refresh "waking up" page
                 └─ browser re-polls every 5s until a poll returns 200
```

- **No third-party WoL package.** The magic packet is ~3 lines of stdlib
  `socket`. The only reason a service exists at all is that `forwardAuth` speaks
  HTTP, not shell.
- **No Traefik restart.** Pure dynamic config (`dynamic/beefy-wake.yml`),
  hot-reloaded.

## Jellyfin: sign in to wake (v1.2.0)

Jellyfin's public route cannot sit behind Authentik (native apps can't log in
there), so internet scanners were booting beefy ~3x/day through it. The gate now
takes `?policy=jellyfin` and decides like this:

| beefy state / request | Result |
|---|---|
| Jellyfin healthy (`/health` = `Healthy`, cached 5 s) | pass (200) |
| not healthy, and a wake campaign is running or sshd already answers | "starting" page, no new wake |
| not healthy, browser navigation (`Accept` contains `text/html`) | "asleep, sign in to start" page, **no wake** |
| not healthy, anything else | wake as before |

The sign-in button leads to the public page
`https://jellyfin.holy-grail.ch/beefy-wake/` -> Traefik router `jellyfin-wake-page`
-> Authentik app `jellyfin-wake` (group `streaming-users`) -> rewritten to `/jf/`.
Only `/jf/*` (page, `/jf/status`, `POST /jf/wake`) is reachable that way; no
`/history`, no admin page. The page wakes beefy, counts down, polls Jellyfin's
`/health` (`JELLYFIN_PORT`, 8096) and redirects to `/web/`.

**Readiness (v1.2.1):** "up" for Jellyfin means its `/health` answers `Healthy`,
not merely that port 8096 is open: measured 2026-10-13, the port opens ~5 s before
Jellyfin can serve (200 with a non-API page, then its own 503). A healthy answer is
reused for 5 s because the gate runs for every request of a video stream; unhealthy
answers are never cached. Side effect: if Jellyfin ever turns unhealthy while beefy
is up, its clients get the "starting" page (no wake is sent, sshd answers).

**Cold start (v1.3.0):** `GET /jf/public-info` (Traefik routes Jellyfin's
`/System/Info/Public` here) relays and caches the server identity. While beefy
sleeps, app requests (never browsers) are held up to 18 s (`HOLD_SECONDS`, max 25;
jellyfin-web times out at 20 s, the Android TV app and Traefik's forwardAuth at
30 s), counted from request arrival; then `/jf/public-info` serves the cached
answer (or 503 without a cache) to native apps only (`Authorization: MediaBrowser`); jellyfin-web's connect check has no such header and it logs the user out if its next authenticated call fails after a fake success, so it gets the waking page instead. A cold boot takes ~50 s, so the idea is staged
holds: each request is held just under its timeout and the app's chain of
retries spans the boot. The identity cache lives in memory and in
`/tmp/public-info.json` (`PUBLIC_INFO_CACHE`): it survives a `docker restart`, not a
container recreate (then the first request after a cold start has no cache until
Jellyfin has been up once). Hold slots are limited (`HOLD_SLOTS`, 16): internet
scanners can occupy them while beefy sleeps, and apps then get the pre-1.3.0
instant 503 until a slot frees.
`observe` lines gain `held` (seconds held), `cached` and `sec_fetch_dest`.

**`observe` log:** one redacted JSON line per Jellyfin request while beefy is down,
plus `/System/Info/Public` while up; never tokens or query values. Read it with:

```bash
sudo grep -a '"observe ' "$(docker inspect -f '{{.LogPath}}' beefy-waker)" | tail
```

Plain `docker logs` stops early because the log file contains NUL bytes from the
2026-09-01 power cut. Purpose: after 1-2 weeks, decide a safe app (native client)
rule (jellyfin-web clients send their first connect check without the Jellyfin header).

Design: `docs/superpowers/specs/2026-10-11-jellyfin-signin-wake-design.md`.

## 2. Manual LAN wake page (`/` and `/wol`)

Open **`https://beefy-wol.fastpi.homelab/`** in a browser:

- **`/`** (root) — shows beefy's **current state** and a big **Wake** button; it does
  **not** wake beefy just because you opened it. Asleep → "beefy is asleep" + Wake
  button; up → "beefy is up and running". It polls `/status` every 3 s and live-updates.
  Pressing **Wake** fires the packet and switches to the countdown.
- **`/wol`** — the one-click variant: on load it **immediately** fires the WoL packet,
  shows a ~`WAKE_COUNTDOWN`s countdown, and polls `/status` until beefy answers.

Both show the collapsed **beefy history** panel and the app version in the footer.

- Routed by Traefik (`dynamic/beefy-wol.yml`) on **websecure with the default
  self-signed cert** (`tls: {}`) — a `.homelab` name can't get a public cert, so
  the browser warns once; fine for a LAN tool. No change to the global 80→443
  redirect.
- **LAN-only:** the hostname is not in the Cloudflare tunnel (so unreachable from
  the internet), and an `ipAllowList` (LAN + bridge ranges) is a second guard.
- **DNS:** add `beefy-wol.fastpi.homelab → 192.168.1.2` to the LAN DNS (router).
  Works immediately without that via `http://fastpi.local:9001/` (mDNS) or
  `http://192.168.1.2:9001/`.

### Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | State + manual wake page (HTML) — shows beefy's status + a Wake button; does **not** auto-wake |
| GET | `/wol` | Same page, but **auto-fires** WoL on load (countdown) |
| GET | `/status` | `{"up": true\|false}` — TCP-probes beefy |
| POST | `/wake` | Fire the WoL magic packet → `{"sent": …}` |
| GET | `/history` | beefy's boot/sleep timeline (JSON) — fetched from its journal |
| GET | `/gate` | forwardAuth gate; `?port=` override (host is hard-wired to beefy) |

### "beefy history" panel

The wake page has a collapsed **"beefy history"** section; opening it lazy-fetches
`/history` and renders a timeline of awake sessions (and the sleeps between them).

`/history` runs a one-shot SSH to beefy using a **read-only forced-command key** —
beefy's `authorized_keys` pins the command to `journalctl --list-boots -o json`, so
the key can do *nothing else* (no pty, no forwarding). beefy's journal is
persistent, so this is real history across reboots. It only loads while beefy is
awake; otherwise the panel shows "history loads once beefy is awake".

**One-time key setup** (run on fastpi; the private key lives in gitignored `secrets/`):
```sh
cd /home/pi/Projects/Docker/Beefy-Waker && mkdir -p secrets
ssh-keygen -t ed25519 -N "" -C beefy-history -f secrets/beefy-history
chmod 600 secrets/beefy-history
ssh-keyscan -t ed25519 192.168.1.102 > secrets/known_hosts
ENTRY="command=\"journalctl --list-boots -o json --no-pager\",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding $(cat secrets/beefy-history.pub)"
ssh beefy "grep -q beefy-history ~/.ssh/authorized_keys || echo '$ENTRY' >> ~/.ssh/authorized_keys"
```

**Starting the history fresh** (drop old/experimental boots, track only from now on):
set `BEEFY_HISTORY_SINCE` (epoch microseconds) in `.env` to the current boot's start,
then `docker compose up -d`. **Non-destructive** — beefy's journal is untouched; old
boots are just filtered out of the panel.
```sh
curl -s http://127.0.0.1:9001/history | python3 -c \
  "import sys,json;print([x for x in json.load(sys.stdin) if x['index']==0][0]['first_entry'])"
# put that number in .env as BEEFY_HISTORY_SINCE=<value>, then: docker compose up -d
```

## Files

| File | Purpose |
|------|---------|
| `app/waker.py` | Gate + status/wake/history endpoints + the manual page. Stdlib only. |
| `app/VERSION` | App version (semver) shown in the page footer. **Bump on each user-facing change.** |
| `Dockerfile` | `python:3.13-alpine` + `openssh-client` (for `/history`), passwd user `waker` = compose uid 65005 (ssh refuses an unknown uid), pip removed (stdlib-only app; pip's vendored libs were the only HIGH CVEs). |
| `docker-compose.yaml` | Builds the image, host network, runs the script. |
| `.env` | MAC, broadcast, probe, port, countdown, ssh user, history cutoff (no secrets). |
| `secrets/` | Read-only history SSH key + `known_hosts` (gitignored). |
| `Traefik/.../dynamic/beefy-wake.yml` | The `beefy-wake` forwardAuth middleware (auto gate). |
| `Traefik/.../dynamic/beefy-wol.yml` | The LAN-only `beefy-wol.fastpi.homelab` route (manual page). |

## Deploy

```sh
cd /home/pi/Projects/Docker/Beefy-Waker
docker compose up -d --build
```

The `beefy-wake.yml` / `beefy-wol.yml` files in Traefik's dynamic dir are picked
up automatically — no Traefik restart. (`/history` needs the one-time key setup in
the "beefy history" section above; the page works without it, just without the panel.)

## Attach to a route

Add the middleware to any beefy-bound router:

```yaml
http:
  routers:
    audiobookshelf:
      # ...
      middlewares:
        - beefy-wake          # wakes beefy before proxying
        - audiobookshelf-secure-headers
```

For precise per-service readiness (instead of "host up" on port 22), point the
probe at the service port via the forwardAuth query string — define a sibling
middleware whose `address` ends in `/?port=<service-port>`.

## Config (`.env`)

| Var | Meaning |
|-----|---------|
| `WAKER_LISTEN_PORT` | Port the gate listens on (host network). Default `9001`. |
| `BEEFY_MAC` | MAC to wake. |
| `BEEFY_BROADCAST` | LAN subnet broadcast (`192.168.1.255`, not `255.255.255.255` — fastpi has many docker bridges). |
| `BEEFY_PROBE_HOST` / `BEEFY_PROBE_PORT` | TCP probe target for "is beefy up". `22` = booted. |
| `WAKE_COUNTDOWN` | Manual page countdown seconds (typical cold boot). Default `60`. |
| `BEEFY_SSH_USER` | SSH user for the `/history` boot-list fetch. Default `buntu`. |
| `BEEFY_HISTORY_SINCE` | Hide boots that started before this epoch-µs cutoff (`0` = show all). See "Starting the history fresh" below. |

## Operations & known limitations

See [`docs/2026-06-26-power-management-review.md`](docs/2026-06-26-power-management-review.md)
for the full adversarial review. The essentials:

**Waking beefy**
- Listen backlog 64 (`request_queue_size`): a burst of parallel requests (Jellyfin home rows) is accepted at once, not retried by the kernel after 1-2 s.
- Automatic: any request to a beefy service routed through the `beefy-wake` middleware.
- Manual: the wake page (`/wol`, or `/` + Wake button), or `wakeonlan 74:56:3c:96:79:a3`
  from fastpi (out-of-band fallback if this container is down).

**Keeping beefy awake / not sleeping when it shouldn't**
- beefy sleeps after **15 min** with no SSH, no VS Code Remote, no inbound service
  connection, and low CPU/net/disk. A **detached low-resource job** (compute, download, a
  paused `apt`) can read as idle → real poweroff mid-job. Before any unattended work:
  `sudo touch /run/beefy-keep-awake` on beefy (clears on reboot; `sudo rm` to release).
- Conversely, **any persistent connection to a service port** (a keepalive monitor, a
  left-open browser tab, an idle WebSocket) pins beefy awake indefinitely.

**Hardening applied 2026-06-26**
- `:9001` binds to the **LAN IP** (`WAKER_BIND`), so the raw port isn't exposed on docker
  bridges / other interfaces (Traefik still reaches it — verified).
- A **Docker `healthcheck`** (`GET /status`) reports liveness. Note: plain compose does **not**
  auto-restart on unhealthy (only crashes/OOM are) — it's for observability + future
  autoheal/swarm.
- A **per-request socket timeout** (`Handler.timeout`) so slow / never-finishing clients can't
  exhaust worker threads.

**Known gaps still open (see review for detail)**
- When attaching `beefy-wake` to a real beefy route, gate on the **service port**
  (`?port=<n>`), not host:22 — else a cold boot / shutdown can 502 instead of the waking page.
  *(Applies only once a beefy service is actually routed.)*
- The waker is a **single point of failure** for automatic wakes; `wakeonlan` from fastpi is
  the out-of-band fallback. (Healthcheck gives observability but not auto-restart in plain compose.)

**Versions:** Beefy-Waker `v1.3.0` (page footer + `app/VERSION`), idle-watcher `v1.1.0`
(its startup log banner).

## SSH wake: `ssh beefy` auto-wakes the box

`ssh beefy` (and `scp`/`rsync`/`git`) transparently wakes beefy when it's asleep — **no script,
no proxy, nothing to install.** It connects straight to beefy and fires the wake over HTTP.
Works on the LAN and over the WireGuard VPN, on macOS / Linux / Windows alike.

Add this to your client's `~/.ssh/config`:

```sshconfig
# Fire the Wake-on-LAN (via the waker) before connecting, then SSH straight to beefy.
Match host beefy exec "curl -fsSk -X POST https://beefy-wol.fastpi.homelab/wake"

Host beefy
    HostName beefy.homelab               # beefy's own name -> 192.168.1.102 (nothing hidden)
    User buntu
    IdentityFile ~/.ssh/your-beefy-key   # your key that's in beefy's authorized_keys
    IdentitiesOnly yes
    ConnectTimeout 5
    ConnectionAttempts 30                # keep retrying the connection while beefy boots (~1 min)
```

**How it works:** the `Match exec` fires one `curl` at the wake URL (sends the WoL packet); then
SSH connects to `beefy.homelab` and `ConnectionAttempts` retries (~1/sec) until beefy's sshd
answers (~1 min later). The address is beefy's real name/IP — the only mention of fastpi is the
wake URL.

**Works because:**
- `curl` is built into macOS, Linux, **and Windows 10+**, and the `Match exec` is a single command
  (no shell pipes), so the *same block* works on Windows too.
- On the LAN the client reaches beefy directly. Over **WireGuard**, the tunnel routes the LAN and
  hands clients **AdGuard** (`192.168.1.2`) as DNS, which resolves `beefy.homelab` ->
  `192.168.1.102` and `beefy-wol.fastpi.homelab` -> `192.168.1.2` — verified on LAN and VPN.
- If a client can't resolve the `.homelab` names, use the IP form for the wake:
  `Match host beefy exec "curl -fsS -X POST http://192.168.1.2:9001/wake"` (and drop the `-k`).

**Behaviour:** an interactive `ssh beefy` keeps beefy awake (the idle-watcher counts it busy); a
one-off `ssh beefy '<cmd>'` wakes, runs, and lets it sleep again ~15 min later. The wake fires on
every connect (a harmless idempotent WoL); use `/gate` instead of `/wake` to only wake when beefy
is actually down.

Verified end-to-end 2026-06-26 — on the LAN and over WireGuard VPN.

## The sleep half (elsewhere)

This project only **wakes** beefy. beefy decides when to **sleep itself** via the
`beefy-idle-watcher` systemd service in the beefy repo
(`Server/8-Idle-Watcher.md`) — it powers off after sustained inactivity, and the
WoL here brings it back.

**Rebuild** (`beefy-waker:local`, FROM `python:3.13-alpine`): `docker compose up -d --build --pull` when Cup shows an update for the base or the security scan lists a fixable base CVE, otherwise monthly. The image has no pip (removed in the `Dockerfile`).

## Nightly maintenance wake

`maintenance-wake/` sends the 03:55 wake. beefy then holds itself awake 03:58-04:45 (`HomeLab-BeefyServer`, `Server/9-Night-Schedule.md`), so the nightly jobs and the fastpi pulls (04:02-04:20, never waking) always find it up.

## Night downloads wake

`night-downloads-wake/` wakes beefy at 22:05 only when downloads wait for the low tariff (Seerr "Can wait", `HomeLab-BeefyServer` `Docker/Movie-Downloads/README.md` "Can wait: downloads at night").

| Unit | When | Does |
|---|---|---|
| `beefy-night-downloads-poll.timer` | every 5 min | Waker `/status` up: `ssh beefy-direct cat ~/.local/state/movie-downloads/night-downloads.json` → `/var/lib/beefy-night-downloads/state.json`. Asleep: nothing, cache kept (never wakes) |
| `beefy-night-downloads-wake.timer` | 22:05 | beefy down and cached `pending > 0`: runs `beefy-maintenance-wake` (Waker gate, wakeonlan fallback). beefy's boot run resumes the downloads |

Why a pull: beefy grabs only while awake and stays up ≥ 15 min after, so a 5-min poll always sees the last count before it sleeps; beefy needs no access to fastpi.

```bash
cd ~/Projects/Docker/Beefy-Waker/night-downloads-wake
sudo install -m 0644 beefy-night-downloads-poll.service beefy-night-downloads-poll.timer beefy-night-downloads-wake.service beefy-night-downloads-wake.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now beefy-night-downloads-poll.timer beefy-night-downloads-wake.timer
./beefy-night-downloads wake --dry-run     # decision now, never wakes
python3 test_beefy_night_downloads.py
```
