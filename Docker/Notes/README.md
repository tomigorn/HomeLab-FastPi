# Notes

Private research notes for one person. MkDocs Material, like the [Wiki](../Wiki/README.md), but the content is **not in this public repo**.

- **URL:** https://notes.holy-grail.ch (Holy Grail SSO, only the user bound to the application)
- **Content:** `NOTES_DIR` in `.env` (`/home/pi/notes`, own local git repo, never pushed; in the fastpi restic backup)
- **Server:** one `caddy:alpine` container serving `$NOTES_DIR/www` read-only, uid 65059

## Add or edit a note

```bash
$EDITOR ~/notes/docs/<topic>.md                 # plus a row in docs/index.md and a nav entry in mkdocs.yml
~/Projects/Docker/Notes/build.sh               # strict build, live at once
git -C ~/notes add -A && git -C ~/notes commit -m "notes: <topic>"
```

## Access

| What | How |
|---|---|
| Provider `notes-proxy`, application `notes` | `../Authentik/scripts/provision-notes-sso.py` |
| Who gets in | a direct **user** binding on the application, no group: `docker compose exec -T -e NOTES_USER=<username> server ak shell < scripts/provision-notes-sso.py` (in `../Authentik`) |
| Test with the canary | `-e CANARY=add`, then `../Authentik/scripts/canary-verify.sh https://notes.holy-grail.ch/ "Research notes"`, then `-e CANARY=remove`; unbound the same check must fail |
| Remove | `-e REMOVE=1` |

## Wiring

```
Internet → Cloudflare Tunnel (route notes.holy-grail.ch → https://192.168.1.2:443, No TLS Verify)
  → Traefik router notes (authentik@file, default-rate-limit, notes-secure-headers: CSP, no-store, noindex)
  → http://notes:80
```

LAN and VPN reach it through the AdGuard `*.holy-grail.ch` rewrite without the tunnel route.

## Deploy

```bash
./build.sh && docker compose up -d
```
