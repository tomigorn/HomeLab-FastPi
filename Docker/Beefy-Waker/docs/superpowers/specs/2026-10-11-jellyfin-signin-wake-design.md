# Jellyfin: sign-in-to-wake for browsers + client-header observation

Date: 2026-10-11 · Status: approved (user, in chat) · Component: Beefy-Waker v1.2.0, Traefik, Authentik

## Problem

`jellyfin.holy-grail.ch` has no Authentik in front of the wake gate (native TV/phone
apps cannot follow a login redirect), so **any** request wakes beefy. Internet scanners
do this ~3×/day (e.g. 2026-10-11 13:30, `45.138.12.28`, 119 secret-file probes in 10 s).
Each wake keeps beefy at ~28 W for ~16 min.

The obvious filter — "only wake when the request carries a Jellyfin client header" —
was checked against source and logs and is **not safe yet**:

- jellyfin-web's `connectionManager.js` sends its first connect check,
  `GET /System/Info/Public`, **without** the `Authorization: MediaBrowser …` header.
  That code runs in browsers, LG/Samsung TV apps and Jellyfin Media Player. A
  header-only rule would mean those clients can never wake beefy.
- Jellyfin fingerprinting bots send exactly that request (6 of ~10 stranger IPs in
  the Traefik log did).
- The other households run "all kinds of hardware", so we cannot pick a rule blind.

## Decision

Two parts, shipped together:

1. **Browser sign-in-to-wake (enforced now).** A browser *navigation* to the Jellyfin
   hostname while beefy is asleep no longer wakes it. It gets an "asleep — sign in to
   start" page. Signing in through Authentik (group `streaming-users`) opens a booting
   page that sends the WoL, counts down, polls readiness of Jellyfin (port 8096) and
   redirects to `/web/` when it answers.
2. **Observe app traffic (log only, no behaviour change).** Every other request still
   wakes beefy exactly as today, so no app regresses. The gate logs a redacted
   fingerprint of the requests that matter, for 1–2 weeks, to choose a safe app rule
   later (separate change).

## Gate behaviour (`/gate`, only when called with `policy=jellyfin`)

Other routes do not pass `policy` and keep today's behaviour byte-for-byte.

| beefy (port probe) | request | response | wakes? |
|---|---|---|---|
| up | any | 200 (pass through) | no |
| down | wake already in progress | 503 "starting, refreshes in 5 s" page | no (campaign already running) |
| down | browser navigation | 503 "asleep — sign in to start" page, button → `/beefy-wake/` | **no** |
| down | anything else | 503 waking page (today's) | yes (today's) |

"Browser navigation" = the original request's `Accept` header contains `text/html`.
Browsers always send that on navigation; jellyfin-web/SDK API calls send
`application/json`, image loaders send `image/*` or `*/*`. Bots that send browser-like
headers fall on the no-wake side, which is the safe direction.

"Wake in progress" = the existing wake campaign is running (`_campaign_running`).

The original request's headers reach the gate because Traefik forwardAuth copies all
request headers when `authRequestHeaders` is unset, and adds `X-Forwarded-Uri`.

## Observation log

One line per observed request, prefix `observe`, JSON payload, written to stdout
(docker json log, like every other waker line). Logged when `policy=jellyfin` and
EITHER beefy is down OR the path is `/System/Info/Public` (case-insensitive). The
second case captures real clients while beefy is up; it is rare (connect checks only),
so volume stays small. Streaming requests while up are NOT logged.

Fields: `up`, `decision` (`pass|starting|signin|wake`), `method`, `path` (no query),
`query_keys` (names only), `auth_mediabrowser` (bool: `Authorization` starts with
`MediaBrowser`), `x_emby_authorization`, `x_emby_token`, `x_mediabrowser_token`
(bools), `client` (the `Client="…"` value from the MediaBrowser header, max 40 chars,
no token), `ua` (User-Agent, max 160), `accept` (max 80), `sec_fetch_mode`,
`ip` (`X-Forwarded-For` first hop).

**Never logged:** header values containing tokens, `Token="…"`, query values
(`api_key`/`ApiKey` carry tokens).

## Browser wake page

Public URL `https://jellyfin.holy-grail.ch/beefy-wake/`, served by the waker under
`/jf/…` (Traefik rewrites the prefix):

- `GET /jf/` — booting page. On load: POST `wake`; countdown from `WAKE_COUNTDOWN`;
  poll `status` every 2 s; when `up` → `location.replace('/web/')`. If already up on
  load → redirect immediately. No history panel, no admin links.
- `GET /jf/status` — `{"up": bool}` probing **port 8096**, not sshd.
- `POST /jf/wake` — same as `/wake` (POST-only).
- anything else under `/jf` → 404.

Uses absolute `/beefy-wake/wake` and `/beefy-wake/status` URLs so it works with or without the trailing slash behind the prefix rewrite.

## Traefik (`dynamic/jellyfin.yml`)

- `jellyfin-outpost`: `Host(jellyfin) && PathPrefix(/outpost.goauthentik.io/)` →
  `authentik@file`, priority 10, no middlewares (as in radarr.yml).
- `jellyfin-wake-page`: `Host(jellyfin) && PathPrefix(/beefy-wake)` → middlewares
  `authentik@file`, `jellyfin-wake-page-rewrite` (replacePathRegex
  `^/beefy-wake/?(.*)` → `/jf/$1`), `jellyfin-secure-headers`; service
  `http://192.168.1.2:9001`; priority 20. Only `/jf/*` is reachable this way — the
  admin page, `/history` and `/gate` are not.
- `jellyfin-wake` middleware address gains `&policy=jellyfin`.
- Main `jellyfin` router unchanged otherwise (still no Authentik, still the gate).

## Authentik

New Proxy Provider `jellyfin-wake` (mode forward_single, external host
`https://jellyfin.holy-grail.ch`) + Application `jellyfin-wake`, policy binding group
`streaming-users` (same as the Jellyfin OIDC app), attached to the embedded outpost.
Config lives in Authentik's DB (not git); record the objects in the Traefik SSO doc.

## Testing

- Unit tests (stdlib unittest, real Handler on an ephemeral port, as in
  `test_waker.py`): each row of the gate table; non-jellyfin policy unchanged;
  observation line present/absent and never contains a token or query value;
  `/jf/` page, `/jf/status` uses 8096, `/jf/wake` POST-only, `/jf/history` 404.
  `is_up` and `send_wol` are patched so no packet is sent.
- Live: gate still 200 while up; `/beefy-wake/` unauthenticated → 302 to
  `sso.holy-grail.ch`; with beefy asleep, a browser-Accept request returns the sign-in
  page and the waker logs no WoL; an `Accept: application/json` request still wakes.
- User: one real sign-in on the phone browser while beefy sleeps.

## Out of scope / later

- The enforced app rule (decide from the observation log after 1–2 weeks).
- Holding app requests until Jellyfin is ready (needs the faster BIOS boot first).
