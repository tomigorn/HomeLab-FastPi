# Ryot (Tracker)

Per-user watch history & ratings that outlive Jellyfin's files. Dashboard tile **Tracker** (Media).

| | |
|---|---|
| URL | https://tracker.holy-grail.ch (Holy Grail, group `streaming-users`) |
| Image | `ghcr.io/ignisda/ryot:v10.5.3`, `postgres:18.6-alpine` |
| Containers | `ryot` (:8000, `ryot_internal` + `traefik_proxy`), `ryot-db` (`ryot_internal` only) |
| Route | `Docker/Traefik/traefik/dynamic/tracker.yml` |
| SSO | `Docker/Authentik/scripts/provision-tracker-sso.py` (apps `tracker`, `tracker-login`) |
| Recommendations | none in Ryot (Pro only); use Seerr's Similar / Recommended |

## Routes

| Path | Gate | Why |
|---|---|---|
| `/outpost.goauthentik.io/` | none | Authentik callback |
| `/_i/<slug>` | `local-networks@file` only | Jellyfin webhook (not a browser); the slug is the secret, tunnel = 403 |
| everything else | `authentik@file`, rate limit, headers | outer gate, then Ryot's own OIDC login |

## Login

- Two steps: Holy Grail forward auth, then Ryot **Sign in with Holy Grail** (OIDC `tracker-login`, redirect `/api/auth`).
- `USERS_DISABLE_LOCAL_AUTH=true`: no passwords. `USERS_ALLOW_REGISTRATION=true`: needed, OIDC users are only created while it is on.
- The **first** user to sign in becomes Ryot admin: the owner signs in first, before any household member.

## Env (`.env`, secrets blank in `.env.example`)

| Key | Value |
|---|---|
| `RYOT_DB_PASSWORD` | secret, also builds `DATABASE_URL` in compose |
| `SERVER_ADMIN_ACCESS_TOKEN` | secret, `openssl rand -hex 32` |
| `SERVER_OIDC_CLIENT_ID`, `SERVER_OIDC_CLIENT_SECRET` | secret, written by `provision-tracker-sso.py` |
| `MOVIES_AND_SHOWS_TMDB_ACCESS_TOKEN` | secret, TMDB "API Read Access Token" |
| `FRONTEND_URL`, `SERVER_OIDC_ISSUER_URL`, `FRONTEND_OIDC_BUTTON_LABEL`, `DISABLE_TELEMETRY=true`, `SERVER_GRAPHQL_PLAYGROUND_ENABLED=false` | as in `.env.example` |

`ryot` has `extra_hosts: sso.holy-grail.ch:192.168.1.2` so OIDC stays on the LAN even without AdGuard.

## Deploy

```bash
cd Docker/Authentik && docker compose exec -T server ak shell < scripts/provision-tracker-sso.py 2>/dev/null | python3 scripts/apply-sso-env.py
cd ../Ryot && docker compose up -d
```

## Backup / restore

- `scripts/ryot-db-backup.sh`: `pg_dump -Fc` to `~/backups/ryot/ryot-YYYY-MM-DD.dump`, keeps 14 days; user timer daily 03:40.
- Install: `cp systemd/* ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now ryot-db-backup.timer`
- Restore (Ryot stopped):

```bash
docker compose stop ryot
docker exec -i -u postgres ryot-db pg_restore -U ryot -d ryot --clean < ~/backups/ryot/ryot-YYYY-MM-DD.dump
docker compose start ryot
```

## Resources (measured)

Budget: Ryot + Postgres ≤ 600 MiB (else move to beefy). `docker stats`, 2026-10-20:

| State | ryot | ryot-db | Sum |
|---|---|---|---|
| 1 min after start | 331 MiB | 65 MiB | 396 MiB |
| 10 min idle | 290 MiB | 59 MiB | 349 MiB |
| after a TMDB search | open (needs the first login) | | |

## Update

Bump `RYOT_TAG` in `.env` and `.env.example`, then:

```bash
Docker/Ryot/scripts/ryot-db-backup.sh
Docker/_global/scripts/update-project.sh Docker/Ryot pull
```
