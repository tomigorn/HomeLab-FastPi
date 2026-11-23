# Navidrome

Music server (Subsonic API), PoC. `https://music.holy-grail.ch`, login only via Holy Grail (Authentik), group `music-users`. Second web UI: Feishin at `/feishin/` (`Docker/Feishin`).

```
Cloudflare Tunnel → Traefik (authentik@file) → navidrome:4533
LAN/VPN: AdGuard *.holy-grail.ch rewrite → Traefik
```

| What | Where |
|---|---|
| Music (HDD, read-only) | `/mnt/seagate-black/library/music` → `/music` |
| DB, cache (NVMe) | `./data` (uid 65062) |
| Settings | `.env` (env vars `ND_*`) |
| Route | `Traefik/traefik/dynamic/music.yml` |
| SSO app "Music" | `Authentik/scripts/provision-music-sso.py` |
| Checks | `_global/post-update.d/Navidrome.sh` |

## Login
- Browser: Holy Grail login; the Navidrome user is created from the Authentik username on the first visit.
- Navidrome trusts `X-authentik-username` only from Traefik (`172.24.255.3`); any other source gets the normal Navidrome login, which no one has a password for.
- Admin: the owner's admin account, created locally before the first SSO login (otherwise the first SSO user becomes admin); its local password is random and discarded.

## Phone
Browser only: no app passwords, so native Subsonic apps (Symfonium, Amperfy, …) can't log in. `/rest` without a Holy Grail session gets the login redirect.

| Web UI | URL |
|---|---|
| Navidrome | `https://music.holy-grail.ch/` |
| Feishin (nicer player, `Docker/Feishin`) | `https://music.holy-grail.ch/feishin/` (first time: Holy Grail username + any text as password) |

Phone browser → "Add to home screen" for an app icon; playback goes on with the screen locked. Removing a user from `music-users` stops new logins at once; a session already open keeps working until it expires (up to 24 h).

## Operate
| Task | Command (fastpi, `~/Projects/Docker`) |
|---|---|
| Start / apply `.env` | `docker compose --project-directory Navidrome up -d` |
| Checks | `_global/scripts/post-update-check.sh Navidrome` |
| Give a user access | Authentik: add to group `music-users` |
| Rescan | nightly 23:30 full scan; the file watcher picks up new files |

Test material: `music/Frédéric Chopin/` (Musopen, CC0), see `SOURCE.txt` there.
