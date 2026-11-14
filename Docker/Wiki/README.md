# Wiki

"Holy Grail Guide": how-to pages for friends (Jellyfin, Requests, audio & subtitles, audiobooks, tracker, profile picture) and a "What's new" page. English, MkDocs Material, no external requests (`theme.font: false`).

- **URL:** https://wiki.holy-grail.ch (Holy Grail SSO, any logged-in user)
- **Server:** one `caddy:alpine` container serving `www/` read-only, uid 65053

## Edit and rebuild

```bash
cd ~/Projects/Docker/Wiki
$EDITOR site/docs/apps/jellyfin.md   # pages: site/docs, menu: site/mkdocs.yml
./build.sh                           # live at once, no restart
```

`build.sh` runs the pinned `squidfunk/mkdocs-material` image (uid 65053, no capabilities, read-only) with `mkdocs build --strict`: a broken link fails the build. Bump `IMAGE` in `build.sh` to update.

## Admin guide

Second site for admins only: https://wiki-admin.holy-grail.ch (Authentik app `wiki-admin`, bound to group `homelab-admins`; friends get no access). Same container: Caddy picks `/srv-admin` for that host name, everything else is the guide.

Add a page: write `site-admin/docs/<name>.md`, add it to `nav` in `site-admin/mkdocs.yml`, run `./build.sh`. Plain simple English, short numbered steps, tables; no secrets, real names, mail addresses or usernames (use `anna`).

## Rules

- **Every user-visible change gets an entry in `site/docs/whats-new.md`** (same change): date heading, newest first, 1–3 lines with what's new, where to click, a link to the detail page; a screenshot where useful (`site/docs/assets/whats-new/`, no personal data: no real names, usernames, mail addresses).
- Menu: sections in `site/mkdocs.yml` `nav` (Start, Watching, Requesting, Audiobooks, Your account, About). Moving a page between sections keeps its URL; renaming a file changes it.

## Files

| File | Purpose |
|---|---|
| `site/mkdocs.yml`, `site/docs/` | the guide (committed) |
| `site-admin/mkdocs.yml`, `site-admin/docs/` | the admin guide (committed) |
| `build.sh` | builds `site/` into `www/` and `site-admin/` into `www-admin/` (both gitignored) |
| `docker-compose.yaml`, `Caddyfile` | the static server |
| `../Traefik/traefik/dynamic/wiki.yml` | route: TLS, rate limit, headers with CSP (own scripts, styles and search worker only; inline script/style allowed because Material needs them) |
| `../Traefik/traefik/dynamic/wiki-admin.yml` | route for the admin host, same headers |
| `../Authentik/scripts/provision-wiki-sso.py` | provider `wiki-proxy`, application `wiki` ("Guide", no group binding) |
| `../Authentik/scripts/provision-wiki-admin-sso.py` | provider `wiki-admin-proxy`, application `wiki-admin` ("Admin guide", bound to `homelab-admins`; `REMOVE = True` undoes it) |

## Wiring

```
Internet → Cloudflare Tunnel (route wiki.holy-grail.ch → https://192.168.1.2:443, No TLS Verify)
  → Traefik router wiki (authentik@file, default-rate-limit, wiki-secure-headers)
  → http://wiki:80
Same for wiki-admin.holy-grail.ch (router wiki-admin, own Cloudflare Tunnel hostname)
```

## Deploy

```bash
./build.sh && docker compose up -d
```

## Recovery when Authentik is down

Same as `../Claude-Mockups/README.md`: read `www/index.html` directly on the server, or add a temporary Traefik router without `authentik@file`, then undo it.
