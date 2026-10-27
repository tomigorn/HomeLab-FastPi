# Avatar Picker

Netflix-style profile pictures for every Authentik user: pick one from a fixed gallery
at `https://avatars.holy-grail.ch` (Holy Grail login). The choice lands in the user's
Authentik attribute `avatar` as `https://sso.holy-grail.ch/avatar-img/img/<id>.png` and
reaches Jellyfin and Nextcloud through the OIDC `picture` claim.

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

## Run

```bash
cd Docker/Avatar-Picker
docker compose up -d --build          # build on fastpi only (local avatar pack in app/img-local/)
python3 scripts/provision-authentik.py  # application, provider, scope (idempotent)
```

Secrets in `secrets/` (gitignored): `authentik_token` (service account `avatar-picker`,
API token), `picker_secret` (the header Traefik adds). Rotate them with `scripts/rotate-secrets.sh token-new` (check a pick) then `token-finish`, and `scripts/rotate-secrets.sh header`; nothing is printed and nobody has to log in again. Gallery sources and licences:
`LICENSES.md`; the gallery is built by `scripts/build-gallery.py`. Tab icon: `app/static/favicon.svg` (the SSO dashboard's Avatar Picker icon); `scripts/build-favicon.py` renders the PNGs.

**Rebuild** (`avatar-picker:local`, FROM `python:3.13-alpine`): `docker compose up -d --build --pull` when Cup shows an update for the base or the security scan lists a fixable base CVE, otherwise monthly.
