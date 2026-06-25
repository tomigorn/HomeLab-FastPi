# Beefy-Waker

Wakes **beefy** (`192.168.1.102`) on demand when a request arrives for any
beefy-hosted service, so beefy can sleep (S5 + WoL) to save power and come back
automatically on first access. Runs on **fastpi**, the always-on Traefik edge.

Part of the [beefy migration](https://github.com/tomigorn/HomeLab-BeefyServer)
wake-on-demand phase. The off/on mechanism (`ssh beefy-poweroff` /
`wakeonlan`) already exists; this is the **wake-on-request** half.

## How it works

Traefik cannot run a script as middleware — a middleware is only a built-in, a
Go plugin, or **`forwardAuth`** (Traefik calls an HTTP endpoint and acts on the
status code). So the whole thing is: a native `forwardAuth` middleware pointing
at a tiny HTTP gate we own.

```
request → Traefik router (a beefy host)
            → forwardAuth: GET http://192.168.1.2:9001/   (this service)
                 ├─ beefy reachable?  TCP-probe 192.168.1.102:22
                 │     yes → 200  → Traefik proxies straight to beefy
                 │     no  → send WoL magic packet to 192.168.1.255:9,
                 │           return 503 + auto-refresh "waking up" page
                 └─ browser re-polls every 5s until a poll returns 200
```

- **No third-party WoL package.** The magic packet is ~3 lines of stdlib
  `socket` (`app/waker.py`). The only reason a service exists at all is that
  `forwardAuth` speaks HTTP, not shell.
- **No Traefik restart.** The middleware is pure dynamic config
  (`Traefik/traefik/dynamic/beefy-wake.yml`), hot-reloaded by the file provider.
- First cold request blocks only as long as the browser keeps refreshing the
  waiting page (~51 s beefy cold boot); no long-held connection, so Cloudflare's
  ~100 s tunnel timeout is never in play.

## Files

| File | Purpose |
|------|---------|
| `app/waker.py` | The gate. Stdlib only, no deps. |
| `docker-compose.yaml` | `python:3.13-alpine`, host network, runs the script. |
| `.env` | MAC, broadcast, probe target, listen port (no secrets). |
| `Traefik/.../dynamic/beefy-wake.yml` | The `beefy-wake` forwardAuth middleware (lives in the Traefik project). |

## Deploy

```sh
cd /home/pi/Projects/Docker/Beefy-Waker
docker compose up -d
```

The `beefy-wake.yml` middleware file is dropped into Traefik's dynamic dir and
picked up automatically — no Traefik restart.

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

## Not included (future)

Idle auto-poweroff is a **separate** task: a timer that calls
`ssh beefy-poweroff` after N minutes of no requests. This project only wakes.
