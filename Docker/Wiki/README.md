# Wiki

"Holy Grail Guide": how-to pages for friends (Jellyfin, Requests, audio & subtitles, audiobooks, tracker, profile picture) and a "What's new" page. English, MkDocs Material, no external requests (`theme.font: false`).

- **URL:** https://wiki.holy-grail.ch (Holy Grail SSO, any logged-in user). Public without login: only `/getting-started/` and its theme assets (`skip_path_regex` in `provision-wiki-sso.py`; page template `site/overrides/public.html` has no menu, search or link into the signed-in wiki, so a click mid-sign-up cannot lose the invite)
- **Server:** one `caddy:alpine` container serving `www/<variant>/` read-only, uid 65053
- **Per group:** everyone sees only what their groups allow, see [Pages per group](#pages-per-group)

## Edit and rebuild

```bash
cd ~/Projects/Docker/Wiki
$EDITOR site/docs/apps/jellyfin.md   # pages: site/docs, menu: site/mkdocs.yml
./build.sh                           # live at once, no restart
```

`build.sh` runs the pinned `squidfunk/mkdocs-material` image (uid 65053, no capabilities, read-only) with `mkdocs build --strict`: a broken link fails the build. Bump `IMAGE` in `build.sh` to update.

## Pages per group

A page or a part of a page can be hidden from people without a group. Pages stay in `site/docs/` once; `build.sh` builds one version per permission level and Caddy picks it from the groups Authentik sends.

| Want | Write |
|---|---|
| whole page only for a group | front matter `groups: [streaming-requesters]` (also hides it from menu and search) |
| part of a page only for a group | `<!-- only: streaming-requesters -->` … `<!-- /only -->` on their own lines |
| text only for people **without** the group | `<!-- only: !streaming-requesters -->` … `<!-- /only -->` |

- A visible page that links to a hidden one fails the build: put the link in an `only` block.
- Known groups: `GATES` in `build.sh` (now `streaming-requesters`). New group: add it to `GATES` (sorted) and a matching `map` in the `Caddyfile`, in the same order; `python3 -m unittest discover -s tests` checks both.
- Each group doubles the builds: `www/base`, `www/base+streaming-requesters`, ….
- Caddy trusts the groups header only from Traefik; anything else, and the public `/getting-started/`, gets `www/base`.

## Admin guide

Second site for admins only: https://wiki-admin.holy-grail.ch (Authentik app `wiki-admin`, bound to group `homelab-admins`; friends get no access). Same container: Caddy picks `/srv-admin` for that host name and answers it only to Traefik (`remote_ip 172.24.255.3`), everything else is the guide.

Add a page: write `site-admin/docs/<name>.md`, add it to `nav` in `site-admin/mkdocs.yml`, run `./build.sh`. Plain simple English, short numbered steps, tables; no secrets, real names, mail addresses or usernames (use `anna`).

## Rules

- **Every user-visible change gets an entry in `site/docs/whats-new.md`** (same change): date heading, newest first, 1–3 lines with what's new, where to click, a link to the detail page; a screenshot where useful (`site/docs/assets/whats-new/`, no personal data: no real names, usernames, mail addresses).
- Menu: sections in `site/mkdocs.yml` `nav` (Start, Watching, Requesting, Audiobooks, Your account, About). Moving a page between sections keeps its URL; renaming a file changes it.

## Files

| File | Purpose |
|---|---|
| `site/mkdocs.yml`, `site/docs/` | the guide (committed) |
| `site-admin/mkdocs.yml`, `site-admin/docs/` | the admin guide (committed) |
| `build.sh` | builds `site/` into `www/<variant>/` per group set and `site-admin/` into `www-admin/` (both gitignored) |
| `site/hooks/groups.py`, `tests/` | drops pages and `only` blocks per build; tests: `python3 -m unittest discover -s tests` |
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
wiki-admin.holy-grail.ch (router wiki-admin): **LAN + VPN only** (`local-networks@file`, owner 2026-11-14), no Cloudflare hostname; then Authentik app `wiki-admin` (homelab-admins only)
```

## Deploy

```bash
./build.sh && docker compose up -d
```

## Recovery when Authentik is down

Same as `../Claude-Mockups/README.md`: read `www/base+streaming-requesters/index.html` directly on the server, or add a temporary Traefik router without `authentik@file`, then undo it.
