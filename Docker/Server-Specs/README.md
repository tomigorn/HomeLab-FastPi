# Server-Specs

Blueprint page of fastpi, beefy and tower (hardware only: no serials, MACs, IPs or firmware versions).

- **URL:** https://specs.holy-grail.ch (Holy Grail SSO, any logged-in user)
- **Server:** one `caddy:alpine` container serving `www/` read-only, uid 65052

## Refresh the snapshot

```bash
cd ~/Projects/Docker/Server-Specs && python3 collect.py && python3 render.py
```

No restart needed. beefy and tower are read over `beefy-direct` / `tower-direct` (never woken); an asleep host keeps its previous entry and date.

## Files

| File | Purpose |
|---|---|
| `collect.py` | reads the hardware into `data/specs.json` (gitignored) |
| `render.py`, `drawings.py` | builds `www/index.html` (gitignored) with inline SVG |
| `test_collect.py`, `test_render.py` | `python3 test_*.py` |
| `docker-compose.yaml`, `Caddyfile` | the static server |
| `../Traefik/traefik/dynamic/server-specs.yml` | route: TLS, rate limit, headers with strict CSP (no scripts) |

## Wiring

```
Internet → Cloudflare Tunnel (route specs.holy-grail.ch → https://192.168.1.2:443, No TLS Verify)
  → Traefik router server-specs (authentik@file, default-rate-limit, server-specs-secure-headers)
  → http://server-specs:80
```

| Piece | Where |
|---|---|
| Cloudflare route | dashboard: Tunnel `fastpi` → published application routes |
| Traefik file | `../Traefik/traefik/dynamic/server-specs.yml` |
| Authentik provider + application | `../Authentik/scripts/` (no group binding) |

## Deploy

```bash
docker compose up -d
```

## Recovery when Authentik is down

Same as `../Claude-Mockups/README.md`: read `www/index.html` directly on the server, or add a temporary Traefik router without `authentik@file`, then undo it.
