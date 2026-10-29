# Audiobook-Requests

Request audiobooks (AudioBookRequest), find them on MyAnonamouse (Prowlarr in `mouse`), copy finished downloads into Audiobookshelf.

- **URL:** https://books.holy-grail.ch (public via the Cloudflare tunnel like Seerr, Holy Grail forward auth + ABR OIDC login, group `streaming-requesters`); navbar link "Movies / Series" → Seerr
- **Roles:** `streaming-admins` = ABR admin, `streaming-requesters` = trusted: every request downloads at once (owner 2026-10-26)
- **Limit:** 5 books per rolling 7 days per person, admins too; the 6th shows ABR's error toast "Limit reached" (API: HTTP 429)
  - deleted requests keep counting (importer ledger `data/quota.json`, filled every minute and on each request); the download buttons that skip a request (wishlist auto-download, API auto-download/download/refresh) are admin only (books-proxy, 403)

## Flow

```
Traefik ──► books-proxy (nginx, .6: Seerr link, request limit via importer /quota) ──► ABR (audiobookrequest, .4)
ABR ── search ──► importer /prowlarr (release policy) ──► prowlarr-gate :9697 ──► prowlarr_mouse 127.0.0.1:9696 (gluetun netns) ──► MAM
ABR grab ──► Prowlarr ──► qbittorrent_mouse, category abr (/downloads/complete, keeps seeding)
ABR webhook onSuccessfulDownload ──► importer /abr (hash, ASIN, title, authors, release title)
importer: torrent complete ──► COPY to library LANG/Author/[Series]/NN - Title ──► M4b-Auto-Merge (several MP3 or M4B parts → one chaptered M4B) ──► ABS scan ──► ABS Audible match (details, cover, authors + image)
```

| Container | uid | Network | Job |
|---|---|---|---|
| `audiobookrequest` | 65055 | `egress`, `traefik_mouse` 10.24.25.4 | request UI (markbeep/audiobookrequest, digest-pinned) |
| `audiobook-importer` | 65056 (+1100) | `egress`, `traefik_mouse` 10.24.25.5 | `importer/` (stdlib Python, `python:3.13-alpine`); callers checked by peer IP (`CALLERS`/`POST_CALLERS`, else 403): `/quota`, `/my-quota`, `/all-requests`, `/library*`, `/sizes` only from books-proxy; `GET /prowlarr/torrent`, `POST /abr`, `POST /prowlarr/*` only from ABR |
| `books-proxy` | 65058 | `traefik_mouse` 10.24.25.6 | `books-proxy/` (nginx-unprivileged, digest-pinned): injects `www/links.js`, the requests bar (`www/bar/`, `www/mam.js`) and `www/sizes.js` before `</head>` ("Movies / Series" next to Wishlist, else a small fixed bar; survives ABR updates), `auth_request` to `/quota` on request endpoints; admits only Traefik (10.24.25.3) and itself (127.0.0.1), every other peer 403, so the `X-authentik-*` headers it trusts always come from Traefik's forward auth |

## Release policy (`importer/ranking.py`, owner's final order 2026-10-26)

ABR has no language, abridged or VIP setting and ranks FLAC above M4B itself, so its Prowlarr URL is the importer's pass-through, which filters, ranks and hands ABR **only the winner** (ABR grabs its first result).

| | Rule |
|---|---|
| filter | requested language only (default EN), no fallback: nothing matches = nothing downloads, the request stays open |
| filter | at least 1 seeder |
| 1 | requested abridgement first (unabridged by default; abridged only when no unabridged release exists) |
| 2 | M4B before FLAC / MP3 |
| 3 | VIP / freeleech before normal |
| 4 | newest upload |

Per request: language and abridged come from the Audible edition picked in ABR (German book = region `de` on the search page, German edition).

Freeleech wedges (owner 2026-10-26): Prowlarr adds `fl=1` to every grab that is not free for us already (freeleech, personal freeleech, VIP-free for a VIP user: skipped, no wedge). If a wedge grab fails (e.g. none left), the pass-through switches the wedge off for one retry as a normal download and back on. ABR's second `.torrent` fetch (for the hash) is answered from qBittorrent (`/torrent` → `torrents/export`), so a grab never hits MAM twice.

## All requests page

`https://books.holy-grail.ch/_hg/requests/` (link "All requests" in ABR's navbar), read-only, same login as ABR: everyone's requests with **who requested** (owner 2026-10-27), date, size, cover and status (open / downloading / in library); sort newest / largest / smallest. Data: importer `GET /all-requests` (ABR's request list + the importer's job states + sizes), served by books-proxy as `/_hg/requests/data.json` (ABR session needed, like the bar); page in ABR's theme (`books-proxy/www/requests/`).

## Sizes on ABR's lists

ABR's Requests and Downloaded tabs get a **Size** column after "Length (hrs)"; clicking it sorts largest → smallest → ABR's order (remembered per browser). `books-proxy/www/sizes.js` (injected) only adds cells and re-orders the existing rows, so ABR's htmx buttons keep working; after an htmx swap it re-applies. Size per ASIN: the Audiobookshelf item (after import and merge), else the qBittorrent torrent while it downloads; `–` = unknown (no ASIN in ABS, or a book the viewer's ABS account may not see: same rules as the Library page, also for the All requests page). Data: importer `GET /sizes` (viewer = `X-authentik-username`) → `/_hg/sizes.json` (ABR session needed).

## Library page

`https://books.holy-grail.ch/_hg/library/` (link "Library" in ABR's navbar, next to All requests): every Audiobookshelf book **the viewer's own ABS account may open** (its library access, explicit flag, tag rules; root/admin all), with cover, title, author, narrator, series, length, size, added date, library and "Open in Audiobookshelf". Search (title, author, narrator, series), sort (newest, title, author, largest, smallest, longest), library filter; one column on phones.

Placement: a books-proxy page under `/_hg/` like All requests, not inside ABR: ABR has no extension point, a page of our own survives ABR updates, and the nav link comes from the same `links.js` injection.

| Part | Where |
|---|---|
| data | importer `GET /library` (viewer = `X-authentik-username`, set by Traefik forward auth; ABS username = the same Holy Grail `preferred_username`, matched exactly) → `/_hg/library/data.json`; covers `GET /library-cover/<id>` (only items the viewer may see, 240 px webp) → `/_hg/library/cover/<id>`. Both need an ABR session (`auth_request`) |
| ABS access | importer's key `audiobook-importer` (ABS admin, GET only here): `/api/libraries`, `/api/libraries/<id>/items?minified=1`, `/api/users` (permissions; tokens and mails never leave the importer); cached 5 min (users 1 min). Keys never reach the browser |
| no ABS account yet | the page says to open Audiobookshelf once (Holy Grail login creates it) |
| page | `books-proxy/www/library/` (`index.html`, `library.js`) |

## Requests bar

The bar Seerr has (requests.holy-grail.ch), on every ABR page and the All requests page. Only after login: Traefik forward auth covers `/_hg/bar/*` (no Holy Grail session → 302 to sso), and books-proxy asks ABR `GET /api/users/me` with the caller's cookie (`auth_request`; no ABR session → 401). `bar.js` draws nothing until `usage.json` answers 200, never on `/login`, `/auth/*`, `/init`; a later 401/redirect removes it.

| Chip | Source |
|---|---|
| MyAnonamouse `searches` / `downloads` (`∞` = no limit) | Prowlarr history, last 24 h; limits per indexer in `abr-bar/limits.toml` (none for MAM) |
| My requests `n/5 in 7 days`, red + "next free" when used up | importer `/my-quota`: the viewer's own count from the quota ledger, nobody else's |
| MAM unsatisfied `n/limit`, red `n at risk` | qBittorrent (read-only Web API, all torrents, MAM = tracker host `*.myanonamouse.net`): seeding time < 72 h and added within 30 days; class + limit in `abr-bar/limits.toml` `[mam]` (MAM rules.php "Unsatisfied torrents": User 50, Power User 100, VIP 150, above 200). No MAM call |
| Next renewal / due subscription | `abr-bar/limits.toml`; `seerr = true` takes the date from Seerr's list (beefy, cached by subscription-alerts); `[mam] vip_expires` adds "MAM VIP" |
| Library, Downloads: used/total, % (`df` numbers) | statvfs of `/mnt/seagate-black/library/audiobooks` and the qBittorrent + SABnzbd download folders; one chip per filesystem (same disk → "Library + Downloads") |

Renewal colours: yellow ≤ 30 days, orange ≤ 7, red on the end date. MAM colours: green < 70 % of the limit, yellow 70–90 %, red ≥ 90 % or any risk.

MAM rule (rules.php 2.5): every download seeds 72 h **in total within 30 days**. Approximation: qBittorrent's `seeding_time` is cumulative since the add (survives restarts), so "< 72 h and added < 30 days ago" = unsatisfied. Risks (red, names under **more**): `paused` (stopped/errored before 72 h), `removed` (gone from qBittorrent before 72 h; remembered in `/var/lib/abr-bar/mam-seen.json`, 0600, until 30 days after the add), `missed` (30 days over, still < 72 h). Next free = the seeding torrent closest to 72 h. qBittorrent down: chip "unavailable", rest unchanged.

VIP end date: `vip_expires = "2027-01-31"` under `[mam]` in `abr-bar/limits.toml` (MAM profile date), picked up within a minute; `""` hides it. When the class changes, update `class` + `unsatisfied_limit` there.

Disk colours: green < 70 %, yellow 70–80 %, red ≥ 80 % (both 1.8 TB HDDs; fastpi's disk alert fires at 85 %, so the bar warns first). Nothing is deleted automatically: torrents seed forever (MAM), the hint says so. Hints and disk names EN/DE (browser language).

| Part | Where |
|---|---|
| collector | `scripts/abr_bar_usage.py`, `systemd/abr-bar-usage.{service,timer}` (every minute, user pi, Prowlarr key + `mouse/secrets/qbit_pass` via `LoadCredential`, network only to the gate 10.24.32.2:9697 and qBittorrent 10.24.25.2:8080) → `/var/lib/abr-bar/usage.json` (names and counts only) |
| served | books-proxy `/_hg/bar/usage.json` (mount `/var/lib/abr-bar`, ro), `/_hg/bar/my-quota.json` (→ importer, user from `X-authentik-username`), `/_hg/bar/bar.{js,css}`; config = `data-ib-*` on the injected `<script>` tag |
| shared code | `books-proxy/www/bar/bar.{js,css}` and `abr-bar/indexer-bar-schema.md` are a vendored, unchanged copy of Seerr's `indexer-bar/www/bar.{js,css}` + `indexer-bar/schema.md` (HomeLab-BeefyServer, canonical). Never edit them here: change them on beefy (both test suites green), commit, then `scripts/sync-bar.sh` here. `--check` compares the sha256 with beefy's HEAD (beefy asleep = skipped, never woken); post-update check `books.bar-shared`. ABR wording (disk names, hints, note) lives in `abr_bar_usage.py` |
| MAM chip | `books-proxy/www/mam.js` (ABR only, injected after `bar.js`): reads `usage.json` `mam` and adds the chip, the **more** section and the bar dot colour after each bar render; `bar.js` ignores the field. `mam` = {`ok`, `unsatisfied`, `limit`, `class`, `level`, `freesAt`, `risks[]` {`name`, `reason`, `seededHours`}, texts `label`/`hint`/`head`/`rule`/`risksHead`/`reasons` EN/DE} |

Install: `sudo install -m 0644 systemd/abr-bar-usage.* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now abr-bar-usage.timer`, then `docker compose up -d books-proxy` (the mount needs `/var/lib/abr-bar`).

## Library naming (`importer/naming.py`)

`EN|DE|Other / First author / [Series without "Series"] / NN - Title`, from the Audible product (title, first author, series + position, language), fallback ABR webhook + MAM language flag. Files keep their download names (library convention, owner 2026-10-26); parts in subfolders are flattened as `CD1 - 01.mp3` because the merger works per folder. An existing folder is never overwritten (`exists` in the job list). Several audio files (MP3 or M4B parts) = `merge-wait` until M4b-Auto-Merge leaves one `.m4b`; only then the scan and match.

## Metadata (ABS)

After the copy (and the merge) the importer scans the language library, then `POST /api/items/<id>/match` (Audible of the request's region, by ASIN: details, cover, narrators, series, genres) and matches every author (description + picture; when the first Audible author ASIN has no picture it tries the other ASINs of the same name). Once per job (`matched` in `data/jobs.json`).

ABR's own "already in library" badge (search results show it, the request button is disabled): ABR's Audiobookshelf URL is `http://audiobook-importer:8000/abs`, which passes only GETs with ABR's read-only key and asks **every** language library (ABR itself knows one). ABR's scan-after-grab POST ends there (404), the importer scans. Checked: this key gets 403 on item PATCH, item match and library scan.

Caveat: the match uses the requested Audible edition; the MAM upload can be another edition (other narrator/year).

## Setup (config as code)

| Step | Command |
|---|---|
| Authentik apps | `Docker/Authentik/scripts/provision-books-sso.py` (README there) → `secrets/abr_oidc_client.json` |
| Prowlarr | `sudo python3 Docker/mouse/scripts/prowlarr-setup.py` |
| ABR settings | `sudo python3 scripts/abr-setup.py` (Prowlarr via policy pass-through, flags, auto-download, webhook, ABS, OIDC) |
| Login check | `bash scripts/verify-login.sh` (canary real login + MFA, ABR OIDC, Seerr link, search; canary disabled afterwards); `PUBLIC=1` = through the Cloudflare tunnel; `QUOTA_ASINS="6 ASINs"` also checks the limit (switch auto-download off first, delete the canary's requests after) |
| Requests bar | `systemd/abr-bar-usage.timer`, see "Requests bar" |
| Tests | `python3 -m unittest discover -s Docker/Audiobook-Requests/importer`; `python3 -m unittest discover -s Docker/Audiobook-Requests/scripts`; bar, MAM chip, sizes, library, all requests, links: `cd books-proxy/tests && npm ci && npm test`; sync: `bash scripts/test_sync_bar.sh` |

## Secrets (`secrets/`, 0400)

| File | Owner | What |
|---|---|---|
| `abr_root_password` | 65055 | ABR root `abr-root` (backup login) |
| `abr_api_key` | pi | ABR API key for `abr-setup.py` |
| `abr_api_key_importer` | 65056 | ABR API key: the importer reads requests (language, abridged) |
| `abr_oidc_client.json` | pi | Authentik client id + secret |
| `qbit_pass` | 65056 | copy of `mouse/secrets/qbit_pass` |
| `abs_api_key` | 65056 | ABS API key `audiobook-importer` (empty = no scan/match) |
| `abs_api_key_abr` | 65055 | ABS API key of the read-only ABS user `abr` (only library + tag access; no download/update/delete/upload, cannot log in) |

ABS API key (by hand): Audiobookshelf → Settings → API Keys → Add API Key, name `audiobook-importer`, a user with **Can Update** (match is a POST) or root, no expiry → `sudo install -o 65056 -g 65056 -m 0400 /dev/stdin secrets/abs_api_key` (paste, Enter, Ctrl-D). Read on every use, no restart. ABS has one library per language folder (`/audiobooks/EN`, `/DE`, `/Other`): the importer scans the one holding the book.

## Recovery

| Problem | Do |
|---|---|
| OIDC broken | `.env` `ABR_FORCE_LOGIN_TYPE=forms`, `docker compose up -d abr`, log in as `abr-root` (`secrets/abr_root_password`); or `/login?backup=1` |
| Import stuck | `data/jobs.json` (state `pending` / `merge-wait` / `done` / `exists` / `failed`), `docker logs audiobook-importer` |

## MAM rules

Searches only on a request (no RSS), session `mam_prowlarr_id` only in Prowlarr, wedges on non-free grabs (never gift / sendWedge / Vault / bonus buys), whole torrents only. Seeding: copies keep the torrent seeding forever; qBittorrent has no global and no `abr` share limit (`prowlarr-setup.py --check` asserts it), nothing is ever stopped or removed for ratio. Prowlarr's hourly `/jsonLoad.php` (VIP check) is owner-approved (2026-10-26).
