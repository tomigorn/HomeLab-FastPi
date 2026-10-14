# Jellyfin stage 2: a cached "main window" while beefy boots — PROPOSAL (not implemented)

Date: 2026-10-14 (night batch) · Status: proposal for the user's decision · Builds on
`2026-10-14-jellyfin-cold-start-hold-design.md` (stage 1 + bounded holds, live as v1.3.x)

## What the night's source research established (jellyfin-web, Android TV, Swiftfin, webOS)

Verified in the clients' code (details in the research notes below):

1. **jellyfin-web logs the user out, permanently, when its authenticated `GET /System/Info`
   fails for ANY reason** — 503, 5xx, timeout or network error — and saves the wiped token to
   localStorage. This is the client behind the browser, the LG webOS app and the Samsung Tizen
   app. It only sends that call after its connect check `GET /System/Info/Public` succeeded.
   Consequence: a gateway must answer `/System/Info` with a **200** or not at all; an 18 s
   hold that ends in a 503 is as bad as an instant 503. (Pre-existing: this already happened
   before v1.3.0 whenever one of these clients was opened while beefy slept.)
2. **Native apps are forgiving.** Android TV: a failed `GET /Users/Me` drops the in-memory
   session but keeps the token; the user sees the user list and a tap retries. Swiftfin makes
   no network call before showing its home screen and logs nobody out on errors.
3. **Timeouts:** jellyfin-web connect check 20 s, other calls none; Android TV 6 s connect /
   30 s request; Swiftfin 20 s idle; **webOS pre-flight 5 s** for `/System/Info/Public` and
   `/web/manifest.json` — an 18 s hold fails there; those two must come from cache in < 5 s.
4. **What a home screen needs (per user):** `/System/Info`, `/Users/{id}` or `/Users/Me`,
   `/DisplayPreferences/usersettings` (+`livetv` on Android TV), `/UserViews`,
   `/UserItems/Resume`, `/Shows/NextUp`, `/Items/Latest?parentId=…`, `/Branding/Configuration`;
   shared: `/web/*` static files, `/web/manifest.json`, images `/Items/*/Images/*` and
   `/Users/*/Images/*` (keyed by URL incl. `tag`).
5. **Must never be faked:** the server `Id` in `/System/Info/Public` (mismatch → "server
   changed" screens), anything that mutates state (`POST /Sessions/Capabilities*`,
   `/DisplayPreferences` writes, playback/progress reports, favourites, auth/logout), and
   `/socket` (clients reconnect on their own).

## Recommendation: a standard caching reverse proxy (nginx) for the read-only start-up calls

Rather than growing the Python waker into a caching proxy, put **nginx with `proxy_cache` +
`proxy_cache_use_stale`** between Traefik and Jellyfin for a whitelist of GET paths. Serving
stale cached responses while the upstream is unreachable is exactly what that feature is for;
it is mature, documented, and needs no code.

- **Where:** a small `Docker/Jellyfin-Cache` project on fastpi (nginx:alpine, Traefik network),
  upstream `192.168.1.102:8096`, cache on disk (e.g. 200 MB, LRU), config-as-code.
- **Cache key per user:** `$request_method$host$uri$is_args$args$http_authorization` for the
  per-user calls (the app's token is in the `Authorization` header, so one user's data can
  never be served to another); key without the header for shared assets/images.
- **Staged waiting falls out of the connect timeout:** beefy fully off → TCP SYN to its IP
  gets no answer → `proxy_connect_timeout 18s` makes nginx wait 18 s, then serve stale (the
  user's "19-second stages"); beefy booting (port closed) → immediate refusal → stale at once;
  Jellyfin up → real answer, cache refreshed. For the webOS pre-flight paths use a 3 s
  location-specific connect timeout.
- **Wake still comes from the gate:** the whitelist router keeps the `jellyfin-wake`
  forwardAuth middleware with `policy=jellyfin&hold=0` (one small waker change: wake, log,
  but return 200 at once so nginx does the waiting). Everything else (playback, writes,
  `/socket`) keeps today's route straight to Jellyfin with the 18 s hold.
- **Then `/jf/public-info` becomes redundant** (nginx caches `/System/Info/Public` too, keeping
  the real `Id`); retire it in the same change to keep one mechanism.

Expected UX after this: open the app while beefy sleeps → after ≤ 18 s the last-seen home
screen appears with posters (from cache) → by the time the user has picked something (~50 s),
beefy is up and playback is real. No logout on web clients because `/System/Info` is replayed.

## Limits and risks to accept

- **First use ever (no cache for that user/token) while beefy sleeps** still ends in the old
  behaviour; for jellyfin-web that is the forced logout. Each user must have opened the app
  once while beefy was up. Mitigation idea for later: the gate could answer `/System/Info`
  for header-less clients with a 503 **before** the connect check succeeds (i.e. keep today's
  "do not serve the cached public info to clients without a MediaBrowser header" rule), so
  web clients see "Server unavailable" instead of being logged out.
- Replayed lists link to items the sleeping server cannot serve yet; a click within the first
  ~50 s gets a held request and possibly an error dialog (not a logout).
- Stale data is at most as old as the user's last visit; `/UserItems/Resume` may show a
  finished item until the real answer replaces it. Harmless.
- nginx is one more container on the Pi (≈ 5–10 MB RAM) and one more hop for ~20 small
  requests per app start; media streams do not pass through it.
- The research covered master/main branches; Tizen and App Store builds lag, but the logout
  behaviour is identical in the 10.11 release branch.

## Decision needed from the user

Build the nginx stale-cache proxy as described (estimated: one compose project, ~80 lines
of nginx config, one waker parameter, a Traefik router; testable with curl and the
throwaway Authentik user)? Or stop at stage 1 and accept: native apps = spinner + one
retry; web-based TV apps = "Server unavailable" (no logout) when opened while beefy sleeps.
