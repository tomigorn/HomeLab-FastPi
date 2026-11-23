# Navidrome

Music server (Subsonic API), PoC. `https://music.holy-grail.ch`, login only via Holy Grail (Authentik), group `music-users`.

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

## Phone apps
Apps can't do the Holy Grail login. Each user creates an **app password** in Holy Grail and uses it as the password in the app; the app sends it as HTTP Basic auth on every request, Authentik checks it.

1. `https://sso.holy-grail.ch/if/user/` → Tokens and App passwords → Create App password (e.g. "Music phone").
2. App: server `https://music.holy-grail.ch`, username = Holy Grail username, password = the app password.
3. Streaming quality on mobile data: Opus 192 kbps; on home Wi-Fi: original.

| Platform | App | Setting |
|---|---|---|
| Android | Symfonium | Subsonic/OpenSubsonic provider, enable "basic auth" (or custom header `Authorization: Basic …`, not both) |
| iPhone | Amperfy (free) | custom header per account `Authorization: Basic <base64 user:app-password>` |

A wrong or expired app password gets the login page, not music: create a new one. Removing a user from `music-users` or deleting an app password cuts access within about 1 min (Authentik cache).

## Operate
| Task | Command (fastpi, `~/Projects/Docker`) |
|---|---|
| Start / apply `.env` | `docker compose --project-directory Navidrome up -d` |
| Checks | `_global/scripts/post-update-check.sh Navidrome` |
| Give a user access | Authentik: add to group `music-users` |
| Rescan | nightly 23:30 full scan; the file watcher picks up new files |

Test material: `music/Frédéric Chopin/` (Musopen, CC0), see `SOURCE.txt` there.
