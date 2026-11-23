# Feishin

Second web UI (music player) for Navidrome. `https://music.holy-grail.ch/feishin/`, login only via Holy Grail (Authentik), group `music-users`, same as Navidrome.

```
Browser → Cloudflare Tunnel → Traefik (authentik@file)
  /feishin/  → feishin:9180 (static app, nginx)
  /rest, /   → navidrome:4533 (the app talks to Navidrome directly, same origin, same login cookie)
```

| What | Where |
|---|---|
| Settings | `.env` (`SERVER_*`, `PUBLIC_PATH`, `ANALYTICS_DISABLED`) |
| Route | `Traefik/traefik/dynamic/music.yml` (`music-feishin`) |
| Checks | `_global/post-update.d/Feishin.sh` |

## First login (once per browser)
1. Open `https://music.holy-grail.ch/feishin/`, log in to Holy Grail.
2. Feishin asks for username and password: **username = your Holy Grail username, password = any text**. Feishin saves it.

Why: Feishin runs in Subsonic mode. Navidrome takes the user from the Holy Grail login (`X-authentik-username`, only from Traefik) and ignores the password Feishin sends. A different username is refused (Navidrome answers "not authorized"), so nobody can type their way into another account.

Navidrome mode is not used: it posts the real Navidrome password to `/auth/login`, which SSO users don't have. Lost in Subsonic mode: Navidrome-only extras such as the smart-playlist editor. Playback, library, playlists, favourites and lyrics work.

## Phone
Same URL in the phone browser; "Add to home screen" for an app icon. Feishin's service worker does not register under `/feishin/` (upstream scope bug), so there is no offline mode.

## Operate
| Task | Command (fastpi, `~/Projects/Docker`) |
|---|---|
| Start / apply `.env` | `docker compose --project-directory Feishin up -d` |
| Checks | `_global/scripts/post-update-check.sh Feishin` |
| Update | bump the tag in `docker-compose.yaml`, `up -d`, checks, log in once in a browser and play a track |
