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
| `Dockerfile` | `python:3.13-alpine` + `openssh-client` (for `/history`). |
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

**Versions:** Beefy-Waker `v1.0.0` (page footer + `app/VERSION`), idle-watcher `v1.1.0`
(its startup log banner).

## SSH wake (optional): make `ssh beefy` auto-wake the box

Two ways — pick per client depending on whether it can SSH to fastpi or just needs the LAN.
Both make `ssh beefy` (and `scp`/`rsync`/`git`/`ssh beefy '<cmd>'`) transparently wake beefy,
with no change to beefy or the waker.

### A) fastpi as jump host — `wake-beefy-connect` (client can reach fastpi, even remotely)

An SSH `ProxyCommand` that runs on fastpi: fires a WoL via the waker (`POST /wake`) if beefy is
down, waits for sshd, then pipes the connection through. The whole session routes via fastpi,
so it works even for clients that can reach **only** fastpi (e.g. remote over VPN).

- **On fastpi:** the script lives here in the repo (executable, tracked). It's referenced by
  absolute path in the client config, so there's **no install step** — it runs straight from
  the repo. Needs `nc` (`netcat-openbsd`).
- **On your client** (`~/.ssh/config`):

  ```
  Host beefy
      HostName 192.168.1.102
      User buntu
      ProxyCommand ssh fastpi /home/pi/Projects/Docker/Beefy-Waker/wake-beefy-connect %h %p
      ConnectTimeout 120
      ServerAliveInterval 30
  ```

  Requires `ssh fastpi` to work from the client (fastpi is the always-on entry — reachable on
  LAN, or remotely via VPN). Your client's own key still authenticates to beefy; the
  ProxyCommand only provides wake + transport.

### B) LAN client, no fastpi SSH — `wake-beefy-client` via `Match exec`

For clients **on the LAN** (can reach beefy directly) but **without** fastpi SSH. The client
connects straight to beefy; only the *wake* goes over HTTP to the waker, which any LAN host can
hit at `http://192.168.1.2:9001`. Needs only `curl` + LAN reachability to `192.168.1.2:9001`
and `192.168.1.102:22` — no fastpi SSH, no DNS, no cert. This is the one to hand to **every
user who needs beefy** but isn't a fastpi admin.

Drop `wake-beefy-client` (in this repo) into the client's `PATH` and reference it:

```
Host beefy
    HostName 192.168.1.102
    User buntu
    ConnectTimeout 15
Match host beefy exec "wake-beefy-client"
```

…or inline it (nothing to install — just paste this block):

```
Host beefy
    HostName 192.168.1.102
    User buntu
    ConnectTimeout 15
Match host beefy exec "curl -fsS --max-time 3 http://192.168.1.2:9001/status | grep -q '\"up\": *true' || { curl -fsS --max-time 5 -X POST http://192.168.1.2:9001/wake >/dev/null 2>&1; n=0; while [ $n -lt 90 ]; do curl -fsS --max-time 3 http://192.168.1.2:9001/status | grep -q '\"up\": *true' && break; n=$((n+1)); sleep 1; done; }; true"
```

### Behaviour (both)

An interactive `ssh beefy` keeps beefy awake (the idle-watcher counts it busy); a one-off
`ssh beefy '<cmd>'` wakes, runs, and lets it sleep again ~15 min later.

Verified end-to-end 2026-06-26: beefy auto-slept, `ssh beefy` fired WoL → ~1 min boot →
connection succeeded.

## The sleep half (elsewhere)

This project only **wakes** beefy. beefy decides when to **sleep itself** via the
`beefy-idle-watcher` systemd service in the beefy repo
(`Server/8-Idle-Watcher.md`) — it powers off after sustained inactivity, and the
WoL here brings it back.
