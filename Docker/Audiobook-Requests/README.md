# Audiobook-Requests

Request audiobooks (AudioBookRequest), find them on MyAnonamouse (Prowlarr in `mouse`), copy finished downloads into Audiobookshelf.

- **URL:** https://books.holy-grail.ch (public via the Cloudflare tunnel like Seerr, Holy Grail forward auth + ABR OIDC login, group `streaming-requesters`); navbar link "Movies / Series" → Seerr
- **Roles:** `streaming-admins` = ABR admin (requests download at once, approves others); everyone else = untrusted (an admin approves each request)

## Flow

```
ABR (audiobookrequest, .4) ── search ──► importer /prowlarr (release policy) ──► prowlarr_mouse (gluetun netns) ──► MAM
ABR grab ──► Prowlarr ──► qbittorrent_mouse, category abr (/downloads/complete, keeps seeding)
ABR webhook onSuccessfulDownload ──► importer /abr (hash, ASIN, title, authors, release title)
importer: torrent complete ──► COPY to library LANG/Author/[Series]/NN - Title ──► M4b-Auto-Merge (multi-file) ──► ABS scan ──► ABS Audible match (details, cover, authors + image)
```

| Container | uid | Network | Job |
|---|---|---|---|
| `audiobookrequest` | 65055 | `egress`, `traefik_mouse` 10.24.25.4 | request UI (markbeep/audiobookrequest, digest-pinned) |
| `audiobook-importer` | 65056 (+1100) | `egress`, `traefik_mouse` 10.24.25.5 | `importer/` (stdlib Python, `python:3.13-alpine`) |

## Release policy (`importer/ranking.py`)

ABR has no language, abridged or "newer" setting and ranks FLAC above M4B, so its Prowlarr URL points at the importer's pass-through, which filters and tags the search results.

| Order | Rule |
|---|---|
| 1 | min 1 seeder |
| 2 | language of the requested Audible edition (default EN); other languages only when none matches |
| 3 | unabridged edition requested → abridged releases dropped |
| 4 | M4B first (FLAC dropped when an M4B exists, then MP3) |
| 5 | newest upload first: flags `abr-newest-1..5` scored 50..10 in ABR (Settings → Download) |

Per request: the language and abridged choice come from the edition picked in ABR. German book = search with region `de` (ABR search page) and pick the German edition.

## Library naming (`importer/naming.py`)

`EN|DE|Other / First author / [Series without "Series"] / NN - Title`, from the Audible product (title, first author, series + position, language), fallback ABR webhook + MAM language flag. Files keep their download names (library convention). An existing folder is never overwritten (`exists` in the job list).

## Setup (config as code)

| Step | Command |
|---|---|
| Authentik apps | `Docker/Authentik/scripts/provision-books-sso.py` (README there) → `secrets/abr_oidc_client.json` |
| Prowlarr | `sudo python3 Docker/mouse/scripts/prowlarr-setup.py` |
| ABR settings | `sudo python3 scripts/abr-setup.py` (Prowlarr via policy pass-through, flags, auto-download, webhook, ABS, OIDC) |
| Navbar link to Seerr | `bash scripts/build-overlay.sh` after every ABR image bump (overlay of the image's own `BaseLayout.jinja`, GPL-3.0) |
| Login check | `bash scripts/verify-login.sh` (canary real login + MFA, ABR OIDC, Seerr link; canary disabled afterwards); `PUBLIC=1` = through the Cloudflare tunnel |
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
| `abs_api_key_abr` | pi | ABS API key `audiobookrequest` (optional, "already in library" check) |

ABS API key (by hand): Audiobookshelf → Settings → API Keys → Add API Key, name `audiobook-importer`, a user with **Can Update** (match is a POST) or root, no expiry → `sudo install -o 65056 -g 65056 -m 0400 /dev/stdin secrets/abs_api_key` (paste, Enter, Ctrl-D). Read on every use, no restart. ABS has one library per language folder (`/audiobooks/EN`, `/DE`, `/Other`): the importer scans the one holding the book.

## Recovery

| Problem | Do |
|---|---|
| OIDC broken | `.env` `ABR_FORCE_LOGIN_TYPE=forms`, `docker compose up -d abr`, log in as `abr-root` (`secrets/abr_root_password`); or `/login?backup=1` |
| Import stuck | `data/jobs.json` (state `pending` / `merge-wait` / `done` / `exists` / `failed`), `docker logs audiobook-importer` |

## MAM rules

Searches only on a request (no RSS), session `mam_prowlarr_id` only in Prowlarr, wedges never used, whole torrents only, copies keep seeding (72 h). ABR re-downloads the `.torrent` once per grab to read its hash (`download.php`, a listed endpoint).
