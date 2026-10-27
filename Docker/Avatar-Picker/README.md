# Avatar Picker

Netflix-style profile pictures for every Authentik user: pick one from a fixed gallery
at `https://avatars.holy-grail.ch` (Holy Grail login). The choice lands in the user's
Authentik attribute `avatar` as `https://sso.holy-grail.ch/avatar-img/img/<id>.png` and
reaches Jellyfin, Seerr and Home Assistant right away, Nextcloud through the OIDC `picture` claim at login (see below).

## Who can see what

| URL | Who | How (Traefik, `Traefik/traefik/dynamic/avatar-picker.yml`) |
|---|---|---|
| `avatars.holy-grail.ch` | every Authentik user | `authentik@file` forward auth + shared-secret header to the container |
| `sso.holy-grail.ch/avatar-img/*` from LAN or VPN | no login | router `avatar-img-local`: `ClientIP()` in the rule + `local-networks@file`. Jellyfin (beefy) and Nextcloud (tower) fetch the images this way |
| `sso.holy-grail.ch/avatar-img/*` from anywhere else | logged-in Authentik users | router `avatar-img-session`: forwardAuth to Authentik's `/api/v3/core/users/me/` with the request's cookies (200 = session, 403 = none). The browser sends the `authentik_session` cookie because the images sit on the sso host, so the avatar shows on the phone away from home. `Cache-Control: private` keeps Cloudflare from caching the image for others |

Nothing is public. Check after a Traefik change (home IP is allowlisted in CrowdSec, so
test both paths):

```bash
H=sso.holy-grail.ch; P=/avatar-img/img/<id>.png; PUB=$(dig +short holy-grail.ch @1.1.1.1 | head -1)
curl -s -o /dev/null -w '%{http_code}\n' --resolve $H:443:$PUB https://$H$P            # 403
curl -s -o /dev/null -w '%{http_code}\n' --resolve $H:443:$PUB -H "Authorization: Bearer <api token>" https://$H$P  # 200
curl -s -o /dev/null -w '%{http_code}\n' --resolve $H:443:192.168.1.2 https://$H$P     # 200 (what beefy/tower do)
```

## How a pick reaches other apps

The pick is stored in Authentik (`attributes.avatar`, the source of truth). Each pick also lands in `data/queue.json` (per user: avatar + time, last pick wins; written by the container, gitignored) and `scripts/avatar-sync.py` pushes it to every app below. Each app is its own target with its own state in `/var/lib/avatar-sync/synced.json`: one app down never blocks the others, a failure stays pending and is retried. A pending pick wakes beefy (Waker `POST :9001/wake`, wait ≤ 3 min for Jellyfin `/jf/status`), at most 3 times per pick; tower is never woken, an inactive target (Nextcloud) is never pending. Mapping: Authentik username → app user. Images: only our local pack (picker URL or the PNG itself).

| App | Supported | How |
|---|---|---|
| Authentik | yes (source) | the picker writes `attributes.avatar`; tenant avatars `attributes.avatar,initials` |
| Jellyfin (beefy) | yes | `ssh -L` (beefy-direct) to `127.0.0.1:8096`, user by name (case-insensitive), `POST /UserImage` with the PNG. Key `secrets/jellyfin_api_key` (Jellyfin API key `avatar-sync`). Also `picture` claim at login |
| Seerr (beefy) | yes | API cannot set an avatar: `scripts/seerr-avatar.py` over ssh on stdin, runs as Seerr's uid 65109. User = `linked_accounts` (provider `holy-grail`). Jellyfin-linked: new `avatarVersion` + empty cache (follows Jellyfin, runs after it). OIDC user: new URL if the old one is a picker URL |
| Home Assistant | yes | websocket `person/update` `picture` = picker URL. Person = id `slug(username)` (`tomigorn-admin` → `tomigorn_admin`) or name equal to the username. Token `secrets/ha_token` (600, long-lived token of `tomigorn-admin`); no file = target inactive, active on the next run once it exists |
| Nextcloud (tower) | prepared, inactive | `ssh tower-direct` → `docker exec -u www-data nextcloud php` → `IAvatarManager` with the PNG on stdin; only while tower's waker says up. Active once `secrets/nextcloud_users.json` (`{"<username>": "<Nextcloud uid = Authentik user uuid>"}`) exists. Until then: `picture` claim at login |
| Audiobookshelf | no | no user pictures |
| AudioBookRequest | no | user model has no picture |
| Grafana | no | avatars are Gravatar only (external, by email) |
| Portainer CE | no | no user pictures |
| Dependency-Track | no | no user pictures |
| Floppy (tracker) | no | no user pictures |
| wg-easy | no | user table has no picture |

| Trigger | What |
|---|---|
| right after a pick (and at boot) | `avatar-sync.path` (queue changed) starts `avatar-sync.service` (user `pi`) |
| every 5 min, only while something is pending | exit 75 = pending: the service starts `avatar-sync.timer`; exit 0 (all applied) stops it. Nothing runs on a schedule when everything is in sync |

No firewall change: only ssh, which HOST-OUT-GUARD already allows, and HA on `127.0.0.1:8123`. On container start, picks made before the queue existed are backfilled.

```bash
journalctl -u avatar-sync.service -n 20                # last pushes
sudo systemctl start avatar-sync.service               # push pending now
python3 scripts/avatar-sync.py --status                # in sync | pending n
python3 scripts/avatar-sync.py --reconcile             # repair: push every pick again (wakes beefy only for a pending pick)
python3 scripts/avatar-sync.py --check ha              # HA pictures vs picks: ok n/n
```

Install (once): `sudo install -d -o 65002 -g 65002 data && sudo cp systemd/avatar-sync* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable avatar-sync.service && sudo systemctl enable --now avatar-sync.path`. Jellyfin key: on beefy `POST /Auth/Keys?app=avatar-sync`, token into `secrets/jellyfin_api_key` (600). HA token: HA as `tomigorn-admin` → Profile → Security → Long-lived access tokens → Create, into `secrets/ha_token` (600).

Nextcloud, once tower is cleared (provider `Nextcloud` sends `sub` = user uuid; `--mapping-uid=sub`):

```bash
cd ../Authentik && echo 'import json; from authentik.core.models import User; print(json.dumps({u.username: str(u.uuid) for u in User.objects.filter(is_active=True, type="internal")}))' | docker compose exec -T server ak shell 2>/dev/null | tail -1 > ../Avatar-Picker/secrets/nextcloud_users.json && chmod 600 ../Avatar-Picker/secrets/nextcloud_users.json
```

## Run

```bash
cd Docker/Avatar-Picker
docker compose up -d --build          # build on fastpi only (local avatar pack in app/img-local/)
python3 scripts/provision-authentik.py  # application, provider, scope (idempotent)
```

Secrets in `secrets/` (gitignored): `authentik_token` (service account `avatar-picker`,
API token), `picker_secret` (the header Traefik adds), `jellyfin_api_key`, `ha_token`, `nextcloud_users.json` (host sync only, not mounted into the container). Rotate them with `scripts/rotate-secrets.sh token-new` (check a pick) then `token-finish`, and `scripts/rotate-secrets.sh header`; nothing is printed and nobody has to log in again. Gallery sources and licences:
`LICENSES.md`; the gallery is built by `scripts/build-gallery.py` (`--missing` renders only new images). Tab icon: `app/static/favicon.svg` (the SSO dashboard's Avatar Picker icon); `scripts/build-favicon.py` renders the PNGs.

**Rebuild** (`avatar-picker:local`, FROM `python:3.13-alpine`): `docker compose up -d --build --pull` when Cup shows an update for the base or the security scan lists a fixable base CVE, otherwise monthly.
