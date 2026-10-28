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
| `audiobook-importer` | 65056 (+1100) | `egress`, `traefik_mouse` 10.24.25.5 | `importer/` (stdlib Python, `python:3.13-alpine`) |
| `books-proxy` | 65058 | `traefik_mouse` 10.24.25.6 | `books-proxy/` (nginx-unprivileged, digest-pinned): injects `www/links.js` before `</head>` ("Movies / Series" next to Wishlist, else a small fixed bar; survives ABR updates), `auth_request` to `/quota` on request endpoints |

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

`https://books.holy-grail.ch/_hg/requests/` (link "All requests" in ABR's navbar), read-only, same login as ABR: everyone's requests with **who requested** (owner 2026-10-27), date, cover and status (open / downloading / in library). Data: importer `GET /all-requests` (ABR's request list + the importer's job states), served by books-proxy as `/_hg/requests/data.json`; page in ABR's theme (`books-proxy/www/requests/`).

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
| Tests | `python3 -m unittest discover -s Docker/Audiobook-Requests/importer` |

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
