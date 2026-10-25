# Wiki

"Holy Grail Guide": how-to pages for friends (Jellyfin, Requests, audio & subtitles, audiobooks, tracker, profile picture). English, MkDocs Material, no external requests (`theme.font: false`).

- **URL:** https://wiki.holy-grail.ch (Holy Grail SSO, any logged-in user)
- **Server:** one `caddy:alpine` container serving `www/` read-only, uid 65053

## Edit and rebuild

```bash
cd ~/Projects/Docker/Wiki
$EDITOR site/docs/apps/jellyfin.md   # pages: site/docs, menu: site/mkdocs.yml
./build.sh                           # live at once, no restart
```

`build.sh` runs the pinned `squidfunk/mkdocs-material` image (uid 65053, no capabilities, read-only) with `mkdocs build --strict`: a broken link fails the build. Bump `IMAGE` in `build.sh` to update.

## Files

| File | Purpose |
|---|---|
| `site/mkdocs.yml`, `site/docs/` | the guide (committed) |
| `build.sh` | builds `site/` into `www/` (gitignored) |
| `docker-compose.yaml`, `Caddyfile` | the static server |
| `../Traefik/traefik/dynamic/wiki.yml` | route: TLS, rate limit, headers with CSP (own scripts, styles and search worker only; inline script/style allowed because Material needs them) |
| `../Authentik/scripts/provision-wiki-sso.py` | provider `wiki-proxy`, application `wiki` ("Guide", no group binding) |

## Wiring

```
Internet → Cloudflare Tunnel (route wiki.holy-grail.ch → https://192.168.1.2:443, No TLS Verify)
  → Traefik router wiki (authentik@file, default-rate-limit, wiki-secure-headers)
  → http://wiki:80
```

## Deploy

```bash
./build.sh && docker compose up -d
```

## Recovery when Authentik is down

Same as `../Claude-Mockups/README.md`: read `www/index.html` directly on the server, or add a temporary Traefik router without `authentik@file`, then undo it.
