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

## 2. Manual LAN wake page (`/`)

Open **`https://beefy-wol.fastpi.homelab/`** in a browser. On load it fires the
WoL packet, shows a ~`WAKE_COUNTDOWN`s countdown to beefy's typical boot time,
polls `/status` in the background, and switches to **"beefy is up and running"**
once it answers.

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
| GET | `/` | Interactive wake page (HTML) |
| GET | `/status` | `{"up": true\|false}` — TCP-probes beefy |
| POST | `/wake` | Fire the WoL magic packet → `{"sent": …}` |
| GET | `/history` | beefy's boot/sleep timeline (JSON) — fetched from its journal |
| GET | `/gate` | forwardAuth gate (`?host=` `?port=` override) |

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

## The sleep half (elsewhere)

This project only **wakes** beefy. beefy decides when to **sleep itself** via the
`beefy-idle-watcher` systemd service in the beefy repo
(`Server/8-Idle-Watcher.md`) — it powers off after sustained inactivity, and the
WoL here brings it back.
