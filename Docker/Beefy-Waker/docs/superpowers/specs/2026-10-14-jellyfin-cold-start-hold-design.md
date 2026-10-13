# Jellyfin cold start: cached server info + held requests (staged waiting)

Date: 2026-10-14 · Status: approved in chat (user: "browser first, you run all the tests";
staging in ~19 s steps is the user's design) · Component: Beefy-Waker v1.3.0, Traefik `jellyfin.yml`

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
- No single held request can bridge 50 s.

## Decision: staged waiting

Each request the app makes is held just under its timeout, so the app's own request chain
spans the boot and the app shows its own spinner the whole time:

- **Stage 1 — connect check.** `GET /System/Info/Public` is routed to the waker
  (`/jf/public-info`). Jellyfin healthy → the waker fetches the real answer, relays it and
  caches it (memory + `/tmp/public-info.json`). Not healthy → same decision rules as the gate,
  then **hold** (rule below); if Jellyfin became healthy → relay the real answer; else if a
  cache exists → **200 cached JSON**; else → the waking page as today. Only 200 answers are
  cached. The app then believes the server is there and proceeds.
- **Stage 2 — the app's start-up calls.** For `policy=jellyfin`, a non-browser request that
  would today get an instant 503 ("starting" or "wake") is **held until Jellyfin is healthy,
  at most `HOLD_SECONDS` (default 18, clamp 0–25)**, polling `/health` every 1 s. Healthy
  within the limit → 200 (pass). Still not healthy → today's 503 page. (Follow-up, not in this
  spec: replay a per-user cached "main window" here instead of the 503, designed from the
  observe log once real app traffic has been seen.)
- **Stage 3 — the real server.** Everything passes once `/health` says Healthy.

Rules shared by both stages:
- The limit is a **deadline measured from the start of the request** (the 1 s TCP pre-probes
  count), and the hold never sleeps or probes past it; worst case ≈ limit + one 1 s probe,
  i.e. < 20 s at the default, well under Traefik's 30 s.
- **Browsers are never held**: a browser navigation gets the sign-in page while down (no wake)
  or the waking page while starting — both immediately.
- The wake decision and its log line are unchanged and happen before the hold.
- **Bounded holds:** at most `HOLD_SLOTS` (default 16, ≥ 1) requests are held at once; beyond
  that the gate answers as today, immediately. Protects the thread-per-request server from
  scanners while beefy sleeps.

Expected UX with stages 1+2 (this spec): app spinner ~36 s → one "connection failed" →
Retry → success (~50–55 s after the first tap). Deterministic; not yet seamless — stage 2's
cached replay is what would remove the error.

## Waker changes (`app/waker.py`, v1.3.0)

- `HOLD_SECONDS` (env, default 18, clamp 0–25), `HOLD_SLOTS` (env, default 16, ≥ 1),
  `HOLD_POLL_SECONDS = 1.0`, `PUBLIC_INFO_CACHE` (env, default `/tmp/public-info.json`).
- `is_jellyfin_ready()` unchanged (5 s positive cache) except any exception → not ready.
- `jellyfin_decision(up, headers) -> "pass"|"starting"|"signin"|"wake"` (today's rules),
  used by `_gate_jellyfin` and `/jf/public-info`.
- `hold_until_ready(host, port, limit, started) -> (ready, seconds_held)`: non-blocking slot
  acquire (no slot → returns at once); polls `is_jellyfin_ready` until True or the deadline
  `started + limit`; releases the slot on every path.
- `_gate_jellyfin`: "wake" → wake + log, then hold; "starting" → hold unless browser;
  held and ready → 200; else 503 page. "signin"/"pass" unchanged. The `observe` line logs the
  original decision and adds `"held": <seconds, 1 decimal>` (0 when not held).
- `GET /jf/public-info`: as in Stage 1; logs an `observe` line with `held` and
  `cached: true|false`. Cache file loaded at startup (`_load_public_info()` in `main()`).

## Traefik (`dynamic/jellyfin.yml`)

- Router `jellyfin-public-info`: ``Host(`jellyfin.holy-grail.ch`) && Path(`/System/Info/Public`)``,
  priority 25, service `beefy-waker-jf`, middlewares `jellyfin-deny-all` (TEMPORARY, same as the
  catch-all while the wizard is unfinished), `jellyfin-public-info-rewrite`
  (replacePathRegex `^/System/Info/Public$` → `/jf/public-info`), `jellyfin-secure-headers`.
- The LAN test host `jellyfin-test.fastpi.homelab` (temporary file, deleted after testing)
  mirrors the public routers without `jellyfin-deny-all`, for end-to-end tests.

## Testing

- Unit (stdlib unittest; `is_jellyfin_ready`/`is_up`/`send_wol`/`_wake_campaign`/`sys.stdout`
  patched, `HOLD_*` patched small): decision table unchanged; hold → 200 when readiness flips;
  503 at the limit; browser never held (down and starting); slot exhaustion → immediate 503;
  slot released after a normal hold and after an exception; clamp of `HOLD_SECONDS` real;
  `/jf/public-info` relay + cache, hold-then-cache while down, no cache → hold then relay/503,
  browser → sign-in page, cache file round-trip; observe `held`/`cached` fields.
- Live, run by Claude, via the LAN test host while beefy sleeps (curl emulating the Android TV
  sequence with a MediaBrowser header): `/System/Info/Public` → held ~18 s then 200 cached JSON
  and one WoL in the waker log; then `/System/Info` → held ~18 s → 503 on a cold start, and 200
  within the hold when beefy is already booting. Browser flow (sign-in → booting page → `/web/`)
  with Playwright and a throwaway Authentik user `claude-test` (TOTP device created via
  `ak shell`, user deleted afterwards).
- The `BeefyWakeLoop` alert may fire during testing (many boots today); acceptable.

## Out of scope

- Any keep-awake / scheduled wake (rejected by the user).
- Changing app timeouts (not configurable in the apps).
- The stage-2 cached replay (follow-up spec after observing real app traffic).
