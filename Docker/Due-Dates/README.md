# Due-Dates

Every date that needs the owner in one place: subscriptions, domains, No-IP confirms, tokens, warranties, reminders. Entered once in `due-dates.toml`, fetched where a provider has an API, read by everything that shows or warns.

## How it fits

| Part | What |
|---|---|
| Source | `due-dates.toml`: the manual dates, one `[[due]]` per item (fields in the file header). No secrets, the repo is public |
| Build | `due_dates.py build` (`due-dates.timer`, every 10 min, file reads only): source + fetched dates → `/var/lib/due-dates/due-dates.json` (merged list) and `fetched.json` (only the fetched values). A broken source keeps the old list |
| Endpoint | `https://due-dates.holy-grail.ch/due-dates.json`: container `due-dates` (caddy, read-only, serves only that file), Traefik `due-dates.yml`, LAN/VPN only (`local-networks@file`), no login, no public DNS name. beefy connects to 192.168.1.2 with that name (SNI) |
| Readers | Telegram: `_global/scripts/subscription-alerts.py` (items with `alert = "telegram"`). Seerr bar (beefy `Seerr/scripts/indexer-usage.py`, `show = ["seerr"]`, via the endpoint, cached). ABR bar (`Audiobook-Requests/scripts/abr_bar_usage.py`, `show = ["books"]`, local file). Grafana / daily digest: `status_exporter.py subscriptions`. Domains and No-IP hostnames for RDAP and the resolve check: `status_exporter.py domains` reads the source. Notes page `claude/due-dates.md` (`Notes/gen-pages.sh`) |

## Where each date comes from

| Kind | Source | API |
|---|---|---|
| Subscriptions (Treasure Maps, Eweka, ProtonVPN, MAM VIP, NZBgeek, NzbPlanet) | manual | none used: no provider offers an end-date API with what is on the host |
| Domain holy-grail.ch | RDAP via `status_exporter.py domains` (daily 05:50, `status_domains.prom`); a `date` set here wins | .ch RDAP has no end date, only the registration anniversary, so the GoDaddy date is set by hand |
| TLS certificates (all routed hostnames) | `status_exporter.py certs` (`status_certs.prom`) | fetched; alerts stay in Prometheus (`expiry.yml`) |
| Authentik API tokens | `authentik_tokens.prom` (weekly rotation) | fetched; alerts stay in Prometheus (`authentik-tokens.yml`) |
| No-IP hostnames | manual: `confirmed` = last confirm day, end = +30 days | none: No-IP has no API for the confirm deadline |
| Docker Hub token | manual | Docker Hub's `GET /v2/access-tokens` refuses a login made with a personal access token (403, tested 2026-11-25); the token on fastpi is one |
| GitHub tokens | manual (none listed yet) | no GitHub token on fastpi |
| Warranties | manual, `kind = "warranty"` (section ready in the source) | - |

## Warnings

| Lead (`lead`) | Stages |
|---|---|
| `[30, 7, 0]` (default) | 🟡 30 days, 🟠 7 days, 🔴 on the date, 🔴 the day after |
| `[5, 3, 1, 0]` (ddns) | 🟡 5, 🟠 3, 🔴 1, 🔴 on the date, 🔴 the day after |
| any list, e.g. `[7, 0]` | first yellow, then orange; 0 = red on the date; the day after always red |

Each stage once per (title, date); a new date starts fresh. `alert = "none"` (default for `kind = "info"`) only lists it. Details: `_global/scripts/README.md` "subscription-alerts".

## Change a date

Edit `due-dates.toml`, commit. The list follows within 10 minutes, the Seerr bar within 20 (its copy is kept 10 min), the notes page on the next notes build. "No-IP confirmed": set `confirmed` for both hostnames.

## Install (once)

```bash
sudo install -m 0644 systemd/due-dates.service systemd/due-dates.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now due-dates.timer
docker compose up -d
```

## Check

| What | Command |
|---|---|
| Tests | `python3 tests/test_due_dates.py` (recorded textfiles in `tests/fixtures`, no live calls) |
| Build | `systemctl start due-dates.service; journalctl -u due-dates -n 5` |
| Page | `python3 due_dates.py md` |
| Endpoint from beefy | `ssh beefy-direct 'curl -s --resolve due-dates.holy-grail.ch:443:192.168.1.2 https://due-dates.holy-grail.ch/due-dates.json \| head'` |
