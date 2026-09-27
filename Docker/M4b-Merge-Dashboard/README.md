# M4b-Merge-Dashboard

A read-only progress page for the audiobook merge run in
`/home/pi/Projects/Docker/audiobookshelf/m4b-merge/`. LAN only.

`orchestrate.py` writes `runs/progress.json` after every finished book; this
project is a `caddy:alpine` container that serves a static page which polls that
file every 5 seconds. There is no backend and nothing to keep in sync — the
container only reads files the orchestrator already writes.

## Where it is

    http://192.168.1.2:8099/

**This is deliberately not reachable from outside the LAN.** The port is bound to
fastpi's LAN address (`BIND_ADDRESS` in `.env`), not `0.0.0.0`, and there is no
Traefik label, no Cloudflare route and no DNS name. That is also why there is no
authentication: nothing off the home network can reach it. If you ever want it
published, it needs auth first — treat adding a Traefik route as a change that
requires that conversation, not a one-liner.

## What it shows

| Element | Meaning |
|---|---|
| Hero percentage | books finished / books queued |
| Meter | merged (blue) vs failed (red) vs remaining (grey track) |
| KPI row | merged, failed, remaining, books/hour, elapsed, net size change |
| In flight | books currently being merged on beefy, with start time |
| Recently finished | last 40, with file count, chapter count, `copy` or `encode`, size change, duration |
| Failures | every failure with its stage and reason |

A `chapters` cell tagged **embedded** means the sources carried their own chapter
tables and they were preserved rather than collapsed to one chapter per file.

The status pill reads `no update in 30 min` if `progress.json` stops advancing,
which is the signal that the run died rather than finished — a finished run sets
`complete` and the pill says `complete`.

Colours come from the validated data-viz palette. The merged/failed pair was
checked with the palette validator in both light and dark mode (worst CVD ΔE 23.8
light / 25.7 dark). Status is always icon + word, never colour alone, so the page
is readable with any form of colour blindness. Dark mode follows the OS setting.

## Operating it

    cd /home/pi/Projects/Docker/M4b-Merge-Dashboard

    docker compose up -d                      # first start
    docker compose up -d --force-recreate     # after editing compose/.env/Caddyfile
    docker compose logs -f                    # if the page won't load

Editing `www/index.html` needs **nothing** — the volume is live and read-only.
Save and reload the browser.

## Notes for future changes

- `www/runs` must exist on the host as an empty directory. It is the mountpoint
  for the orchestrator's `runs/` dir, nested inside the read-only `www` bind;
  with `read_only: true` the container cannot create it itself.
- `cap_add: NET_BIND_SERVICE` is required even though the container binds :8080.
  The caddy binary carries that capability as a *file* capability, and
  `cap_drop: ALL` empties the bounding set, which makes the kernel fail `execve`
  with EPERM. This is not optional hardening slack.
- The tmpfs mounts for `/config` and `/data` need `mode=0777` because the
  container runs as uid 1000 and caddy writes bookkeeping there even with TLS off.

## Files

| File | Purpose |
|---|---|
| `docker-compose.yaml` | the caddy service, LAN port binding, hardening |
| `.env` / `.env.example` | bind address, port, image tag, path to the runs dir |
| `Caddyfile` | static file serving, `/healthz`, no-store on the live JSON |
| `www/index.html` | the whole page — self-contained, no CDN |
| `www/runs/` | empty mountpoint for the orchestrator's `runs/` directory |
