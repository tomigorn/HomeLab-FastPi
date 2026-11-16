# Miniflux

[Miniflux](https://miniflux.app) `2.3.5` (Apache-2.0) as the reader for the CVE feeds of [Vulnerability-Lookup](../Vulnerability-Lookup/README.md) and the release notes of what we run. New entries go to Telegram.

- **URL:** https://news.holy-grail.ch (Holy Grail SSO, groups `homelab-admins` and `homelab-users`). Cloudflare public hostname created by the owner 2026-11-16.
- Login = the forwarded `X-authentik-username`, trusted only from Traefik's `172.24.255.3`. Local login off. A Holy Grail user gets a Miniflux account on the first visit.
- `MINIFLUX_ADMIN` (`.env`, a Holy Grail username) owns the feeds and the Telegram integration; every other user gets a copy of the feeds (see Users).
- `miniflux` (distroless, uid 65066, read-only, 128 MB) + `miniflux-db` (`postgres:18.7-alpine`, uid 70, 192 MB). API on `127.0.0.1:8097` for the scripts only.

| Category | Feeds |
|---|---|
| Watchlist | Vulnerability-Lookup watchlist (`../Vulnerability-Lookup/watchlists.toml`), one entry per vulnerability |
| KEV | CISA Known Exploited Vulnerabilities (local copy, synced from vulnerability.circl.lu) |
| Releases | GitHub releases/tags of 34 components (`feeds.toml`) |

The Vulnerability-Lookup feeds are read over `vl_feeds` (internal, no SSO); `FETCHER_ALLOW_PRIVATE_NETWORKS=1` is needed for that, `HTTP_CLIENT_TIMEOUT=120` because the watchlist is computed per request (up to ~30 s while a feeder imports).

## Users

| What | How |
|---|---|
| Account | created on the first visit (`AUTH_PROXY_USER_CREATION=1`) |
| Feeds, categories | same as `MINIFLUX_ADMIN`: `scripts/sync_users.py`, every 5 min (`miniflux-feed-sync.timer`), so up to 5 min after the first visit |
| Admin adds / moves / removes a feed | follows on the next run; a feed or category the user added himself stays |
| User removes a synced feed | comes back on the next run |
| Read state, settings | per user |
| Telegram | admin only, never copied (no double messages) |

Each user is reached with its own API key "feed-sync" (derived from `secrets/api_key`). Run by hand: `Docker/Miniflux/scripts/sync_users.py`; log: `journalctl -u miniflux-feed-sync`. Removing a user from the Authentik groups does not delete the Miniflux account (Settings → Users).

## Telegram

The homelab bot and alert chat (`../_global/secrets/oob-alert.env`, token file of Alertmanager's bot). Every new entry of every feed is sent (Miniflux has no per-feed switch). Only on `MINIFLUX_ADMIN`. Set or change: `scripts/setup.sh telegram`. Off: Settings → Integrations → Telegram in the UI.

## Secrets (`secrets/`, gitignored)

| File | Owner, mode | What |
|---|---|---|
| `miniflux_db_url` | 65066 0400 | `postgres://miniflux:<pw>@miniflux-db/miniflux?sslmode=disable` |
| `miniflux_db_password` | 70 0400 | same password |
| `miniflux_admin_password` | 65066 0400 | required by `CREATE_ADMIN`, never used (local login off) |
| `api_key` | pi 0600 | API key "subscribe.py" (row in `api_keys`) |
| `feed_key` | pi 0600 | Vulnerability-Lookup watchlist feed key |
| `feed_sync_state.json` | pi 0600 | which feeds and categories `sync_users.py` gave each user (feed URLs incl. the feed key) |

## Install

```
docker compose --project-directory Docker/Miniflux up -d       # after Docker/Vulnerability-Lookup (network vl_feeds)
Docker/Miniflux/scripts/setup.sh api-key
Docker/Miniflux/scripts/setup.sh feed-key
Docker/Miniflux/scripts/subscribe.py
Docker/Miniflux/scripts/setup.sh telegram      # after the first fetch, or every old entry is sent
sudo cp Docker/Miniflux/systemd/miniflux-feed-sync.* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now miniflux-feed-sync.timer
Docker/_global/scripts/post-update-check.sh Miniflux
```

More feeds: add to `feeds.toml`, `scripts/subscribe.py` (adds, moves, never deletes; `--dry-run` first).

## Tests

```
python3 -m unittest discover -s Docker/Miniflux/tests
bash Docker/Miniflux/tests/test_setup.sh
```

## Notes

- Not backed up: read state only; feeds come back with `subscribe.py` and `sync_users.py`.
- Every user's feeds are fetched separately: the watchlist feed (up to ~30 s) once per user per hour.
- Migrates its DB at start (`RUN_MIGRATIONS=1`): updates are `notify` in `../_global/auto-update.conf` with a volume backup first.
- `qdm12/gluetun` moved to `passteque/gluetun` (GitHub redirect); Miniflux refuses the old URL as a duplicate.
