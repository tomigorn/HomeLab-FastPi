# Miniflux

[Miniflux](https://miniflux.app) `2.3.5` (Apache-2.0) as the reader for the CVE feeds of [Vulnerability-Lookup](../Vulnerability-Lookup/README.md): High and Critical only (CVSS >= 7.0, owner 2026-11-16). New entries go to Telegram.

- **URL:** https://news.holy-grail.ch (Holy Grail SSO, groups `homelab-admins` and `homelab-users`). Cloudflare public hostname created by the owner 2026-11-16.
- **Tech stack page:** https://news.holy-grail.ch/techstack ([CVE-Techstack](../CVE-Techstack/README.md)), last item of the header menu.
- Login = the forwarded `X-authentik-username`, trusted only from Traefik's `172.24.255.3`. Local login off. A Holy Grail user gets a Miniflux account on the first visit.
- `MINIFLUX_ADMIN` (`.env`, a Holy Grail username) owns the feeds and the Telegram integration; every other user gets a copy of the feeds (see Users).
- `miniflux` (distroless, uid 65066, read-only, 128 MB) + `miniflux-db` (`postgres:18.7-alpine`, uid 70, 192 MB). API on `127.0.0.1:8097` for the scripts only.

| Category | Feed (`feeds.toml`) |
|---|---|
| Watchlist | `http://vl-severity-feed:8080/watchlist.atom`: watchlist (`../Vulnerability-Lookup/watchlists.toml`), one entry per vulnerability |
| KEV | `http://vl-severity-feed:8080/kev.atom`: CISA Known Exploited Vulnerabilities (synced from vulnerability.circl.lu) |

- Both only with a CVSS base score >= 7.0 (highest of CVE record, NVD, GitHub advisory; GitHub HIGH/CRITICAL counts). No score yet: the entry comes when one >= 7.0 arrives, dated then. Filter: [Severity feed](../Vulnerability-Lookup/README.md#severity-feed-high-and-critical-only).
- Title: `❗ Grafana · CVE-2024-9264 · CVSS 9.9 (CNA "Grafana Labs")`; the mark shows the status in the list: ❗ action needed, ❔ ours, check by hand, ✅ ours, not affected, ℹ️ not our product.
- Each entry starts with a status block (our product, affected version, action needed): [Status block](../Vulnerability-Lookup/README.md#status-block-owner-2026-11-16). A status change rewrites title and content of the known entry on the next fetch (read state stays); no second Telegram message.
- Releases (GitHub release notes) dropped 2026-11-16 (owner).
- Read over `vl_feeds` (internal, no SSO); `FETCHER_ALLOW_PRIVATE_NETWORKS=1` is needed for that, `HTTP_CLIENT_TIMEOUT=120` stays from the direct watchlist feed.

## Users

| What | How |
|---|---|
| Account | created on the first visit (`AUTH_PROXY_USER_CREATION=1`) |
| Feeds, categories | same as `MINIFLUX_ADMIN`: `scripts/sync_users.py`, every 5 min (`miniflux-feed-sync.timer`), so up to 5 min after the first visit |
| Admin adds / moves / removes a feed | follows on the next run; a feed or category the user added himself stays |
| User removes a synced feed | comes back on the next run |
| Admin's copy fetched newer (new titles, status) | the user's copy is refreshed on the next run (fetched more than 1 min before the admin's) |
| Read state, settings | per user |
| "Tech stack" header link | every user, admin included: custom JavaScript block in the user's settings, set by `sync_users.py`; own custom JavaScript stays |
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
| `feed_sync_state.json` | pi 0600 | which feeds and categories `sync_users.py` gave each user |

The watchlist feed key moved to `../Vulnerability-Lookup/secrets/feed_key` (2026-11-16): only `vl-severity-feed` reads the watchlist.

## Install

```
docker compose --project-directory Docker/Miniflux up -d       # after Docker/Vulnerability-Lookup (network vl_feeds)
Docker/Miniflux/scripts/setup.sh api-key
Docker/Miniflux/scripts/subscribe.py
Docker/Miniflux/scripts/setup.sh telegram      # after the first fetch, or every old entry is sent
sudo cp Docker/Miniflux/systemd/miniflux-feed-sync.* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now miniflux-feed-sync.timer
Docker/_global/scripts/post-update-check.sh Miniflux
```

More or fewer feeds: edit `feeds.toml`, then `scripts/subscribe.py --dry-run --prune`, then without `--dry-run` (adds, moves; `--prune` also removes unlisted feeds and emptied categories; without it nothing is deleted). Other users follow within 5 min.

## Tests

```
python3 -m unittest discover -s Docker/Miniflux/tests
bash Docker/Miniflux/tests/test_setup.sh
```

## Notes

- Not backed up: read state only; feeds come back with `subscribe.py` and `sync_users.py`.
- Every user's feeds are fetched separately, once per user per hour, plus once after each admin fetch (cheap: `vl-severity-feed` serves from memory). `POLLING_FREQUENCY=15` is the scheduler tick: with 60 it missed feeds due at the same minute by milliseconds and fetched them every 2 h.
- Migrates its DB at start (`RUN_MIGRATIONS=1`): updates are `notify` in `../_global/auto-update.conf` with a volume backup first.
