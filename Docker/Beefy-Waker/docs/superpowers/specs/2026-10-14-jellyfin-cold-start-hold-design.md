# Jellyfin cold start: cached server info + held requests

Date: 2026-10-14 · Status: approved in chat (user: "browser first, you run all the tests") ·
Component: Beefy-Waker v1.3.0, Traefik `jellyfin.yml`

## Problem

A Jellyfin app opened while beefy sleeps gets an instant "server unavailable": the gate
answers 503 within ~2 s, and the app has no waiting UI. A cold wake takes ~50 s to a healthy
Jellyfin (measured 2026-10-13: WoL→sshd 48 s, →`/health` 50 s; BIOS tuning is closed, see
memory). The user rejects keeping beefy awake; the waiting experience is what may improve.

Hard limits found before designing:
- Traefik's forwardAuth client has a **fixed 30 s timeout** (`pkg/middlewares/auth/forward.go`,
  `Timeout: 30 * time.Second`). A gate response slower than that becomes a 500.
- Jellyfin Android TV (Kotlin SDK): 6 s connect, **30 s per request**. jellyfin-web: the
  connect check `GET /System/Info/Public` has a **20 s** timeout; all other requests have none.
- No single held request can bridge 50 s. The achievable outcome is: the app shows its own
  spinner instead of an instant error, and **the first retry succeeds** (today a retry inside
  the boot window fails again instantly).

## Decision

1. **Cached server identity.** `GET /System/Info/Public` on the Jellyfin hostname is routed to
   the waker (new `/jf/public-info`). Jellyfin healthy → the waker fetches the real answer,
   relays it, and caches it (memory + `/tmp/public-info.json`). Jellyfin not healthy → the
   waker applies the same decision as the gate (below) and, instead of a waking page, returns
   the **cached JSON immediately** (200). The app then believes the server is there and
   proceeds; with no cache yet (fresh waker, beefy never seen) it falls back to the gate
   behaviour.
2. **Held requests.** For `policy=jellyfin`, a non-browser request that would today get an
   instant 503 ("starting" or "wake") is instead **held until Jellyfin is healthy, at most
   `HOLD_SECONDS` (default 25)**, polling `/health` every 1 s. Healthy within the limit → 200
   (pass). Still not healthy → today's 503 page. Browser navigations are unchanged (sign-in
   page, no wake). The wake decision/log line is unchanged and happens before the hold.
3. **Bounded holds.** At most `HOLD_SLOTS` (default 16) requests are held at once; beyond that
   the gate answers as today, immediately. Protects the thread-per-request server from
   scanners while beefy sleeps.

Expected UX on a cold start: TV app spinner ~25 s → "connection failed" → Retry → success
(~50–55 s after the first tap). Phone/web clients similar. Not seamless; deterministic.

## Waker changes (`app/waker.py`, v1.3.0)

- `HOLD_SECONDS` (env, default 25, clamp ≤ 28), `HOLD_SLOTS` (env, default 16).
- `is_jellyfin_ready()` unchanged (5 s positive cache).
- Decision logic extracted: `jellyfin_decision(up, headers) -> "pass"|"starting"|"signin"|"wake"`
  (same rules as today), used by `_gate_jellyfin` and `/jf/public-info`.
- `hold_until_ready(port, limit) -> bool`: acquires a slot (non-blocking); without a slot
  returns False at once; otherwise polls `is_jellyfin_ready` every 1 s until True or limit.
- `_gate_jellyfin`: decision "wake" → wake + log (as today) then `hold`; "starting" → `hold`;
  held and ready → 200; else today's 503 page. "signin"/"pass" unchanged. The `observe`
  line gains `"held": <seconds, 1 decimal>` (0 when not held).
- `GET /jf/public-info`: healthy → `urllib` GET `http://PROBE_HOST:JELLYFIN_PORT/System/Info/Public`
  (timeout 3 s), relay status/body as `application/json`, save cache. Not healthy → decision
  via `jellyfin_decision`: "signin" (a browser) → 503 sign-in page; "wake" → wake + log; then
  if cache exists → 200 cached JSON (no hold); else → `hold`, then 200 relay or 503 page.
  Logs an `observe` line (decision + `cached: true|false`). Never caches non-200 answers.
- Cache file `/tmp/public-info.json` loaded at startup if present.

## Traefik (`dynamic/jellyfin.yml`)

- New router `jellyfin-public-info`: ``Host(`jellyfin.holy-grail.ch`) && Path(`/System/Info/Public`)``,
  priority 25, service `beefy-waker-jf`, middlewares `jellyfin-deny-all` (TEMPORARY, same as the
  catch-all while the wizard is unfinished), `jellyfin-public-info-rewrite`
  (replacePathRegex `^/System/Info/Public$` → `/jf/public-info`), `jellyfin-secure-headers`.
- The LAN test host `jellyfin-test.fastpi.homelab` (temporary file, deleted after testing)
  mirrors the public routers without `jellyfin-deny-all`, for end-to-end tests.

## Testing

- Unit (stdlib unittest, `is_jellyfin_ready`/`send_wol`/`time` patched): decision table
  unchanged; hold returns 200 when readiness flips during the hold; returns 503 at the limit;
  slot exhaustion → immediate 503; `/jf/public-info` relay + cache + cached-while-down + no
  cache → hold; browser → sign-in page; observe `held`/`cached` fields; cache file round-trip.
- Live, run by Claude, via the LAN test host while beefy sleeps (curl emulating the Android TV
  sequence: `/System/Info/Public` with MediaBrowser header → expect cached 200 fast; then
  `/System/Info` → expect a hold of ~25 s then 503 on a cold start, and 200 within the hold
  when beefy is already booting). Browser flow (sign-in → booting page → `/web/`) with
  Playwright and a throwaway Authentik user `claude-test` (TOTP device created via `ak shell`,
  user deleted afterwards).
- Keep: the `BeefyWakeLoop` alert must stay quiet during tests (≤ 20 state changes / 24 h —
  today's BIOS tests already produced many; expect a warning, acceptable).

## Out of scope

- Any keep-awake / scheduled wake (rejected by the user).
- Changing app timeouts (not configurable in the apps).
