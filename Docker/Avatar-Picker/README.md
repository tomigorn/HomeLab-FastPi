# Avatar Picker

Netflix-style profile pictures for every Authentik user: pick one from a fixed gallery
at `https://avatars.holy-grail.ch` (Holy Grail login). The choice lands in the user's
Authentik attribute `avatar` as `https://sso.holy-grail.ch/avatar-img/img/<id>.png` and
reaches Jellyfin and Nextcloud through the OIDC `picture` claim, and Jellyfin and Seerr right away (see below).

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

Jellyfin and Nextcloud read the `picture` claim only at their next login, so each pick also lands in `data/queue.json` (per user: avatar + time, last pick wins; written by the container, gitignored) and a host job pushes it. It never wakes beefy.

| Step | What |
|---|---|
| Trigger | `avatar-sync.path` (queue changed = right after a pick) and `avatar-sync.timer` (every 5 min) start `avatar-sync.service` (user `pi`), `scripts/avatar-sync.py` |
| beefy asleep | Waker `http://192.168.1.2:9001/status` not `{"up": true}`: nothing is sent, the pick stays queued |
| Jellyfin | over `ssh -L` (beefy-direct) to beefy's `127.0.0.1:8096`: user by name (case-insensitive), `POST /UserImage?userId=` with the PNG. Key: `secrets/jellyfin_api_key`, Jellyfin API key `avatar-sync` (Jellyfin keys are all admin; this one is revocable on its own) |
| Seerr | Seerr's API cannot set an avatar, so `scripts/seerr-avatar.py` goes over ssh on stdin and runs on beefy as Seerr's uid 65109. User = `linked_accounts` (provider `holy-grail`). Jellyfin-linked (owner): new `avatarVersion` + empty avatar cache, Seerr re-fetches Jellyfin's image. OIDC user: new URL, only if the old one is a picker URL |
| Done | `/var/lib/avatar-sync/synced.json`; a failure stays queued and is retried |
| Nextcloud (tower) | not wired yet: still at the next login |

No firewall change: only ssh, which HOST-OUT-GUARD already allows. On container start, picks made before the queue existed are backfilled.

```bash
journalctl -u avatar-sync.service -n 20      # last pushes
sudo systemctl start avatar-sync.service     # push now
```

Install (once): `sudo install -d -o 65002 -g 65002 data && sudo cp systemd/avatar-sync.* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now avatar-sync.path avatar-sync.timer`. Jellyfin key: on beefy `POST /Auth/Keys?app=avatar-sync`, token into `secrets/jellyfin_api_key` (600).

## Run

```bash
cd Docker/Avatar-Picker
docker compose up -d --build          # build on fastpi only (local avatar pack in app/img-local/)
python3 scripts/provision-authentik.py  # application, provider, scope (idempotent)
```

Secrets in `secrets/` (gitignored): `authentik_token` (service account `avatar-picker`,
API token), `picker_secret` (the header Traefik adds), `jellyfin_api_key` (host sync only, not mounted into the container). Rotate them with `scripts/rotate-secrets.sh token-new` (check a pick) then `token-finish`, and `scripts/rotate-secrets.sh header`; nothing is printed and nobody has to log in again. Gallery sources and licences:
`LICENSES.md`; the gallery is built by `scripts/build-gallery.py` (`--missing` renders only new images). Tab icon: `app/static/favicon.svg` (the SSO dashboard's Avatar Picker icon); `scripts/build-favicon.py` renders the PNGs.

**Rebuild** (`avatar-picker:local`, FROM `python:3.13-alpine`): `docker compose up -d --build --pull` when Cup shows an update for the base or the security scan lists a fixable base CVE, otherwise monthly.
