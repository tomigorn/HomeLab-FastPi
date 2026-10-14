# Night batch 2026-10-14 — Jellyfin cold start on a sleeping beefy

Written 02:50 for the morning. Everything below ran unattended after the user went to bed;
beefy is back to sleeping when idle (last wake 02:49 by the browser test, idles off ~03:05).

## What was done

1. **Live tests of the staged cold start (Beefy-Waker v1.3.0 + review fixes, deployed).**
   - Test B (cold start, cache present, native-app headers) — measured twice, same result:
     connect check held **18 s → 200 cached**; `/System/Info` held **18 s → 503**, again
     **17 s → 503**; real Jellyfin at **t ≈ 57 s**.
   - Browser flow (Playwright, real Authentik login with a throwaway user): `/web/` while
     asleep → sign-in page, **no wake** → Authentik (user / password / TOTP) → booting page →
     wake logged as `jf wake by claude-test` → redirect into Jellyfin **55 s** after the wake
     (lands on 403 only because the public hostname is still closed — expected).
2. **Code review of the whole v1.3.0 change set** (subagent) → 14 findings, all fixed:
   relay/caching hardened (all exceptions caught, only a JSON object with `Id` is cached, atomic
   file write, no rewrite when unchanged, remaining-time budget so the connect check stays
   under 20 s), CORS header on the cached answer, router GET-only and case-insensitive, browsers
   never held anywhere, clamp helpers instead of a module reload in tests, docs/`.env.example`
   updated. 74 unit tests pass.
3. **Source research of the Jellyfin clients' start-up sequences** (jellyfin-web, Android TV,
   Swiftfin, webOS) → one important finding, see below, and a written stage-2 proposal.
4. **Housekeeping:** temporary LAN test route deleted, throwaway Authentik user `claude-test`
   deleted, credentials file removed. Nothing pushed (as instructed).

Commits tonight (all local, on `main`): `e99034f`, `b74e350`, `1b799fd`, `2385cc8`, `5f84c5b`,
`a5306fb`, `5dc5c49`, `3fbd5c3`, `5f1b405`, this summary. (`cbefd23` "Tower-Waker: document…"
at 00:34 is not from this session.)

## What worked

- The staged waiting behaves exactly as designed, deterministically, on every run.
- The browser path is now verified end to end, including the real Authentik login.
- Found and fixed a real hole before it mattered: a browser's **favicon request** after the
  sign-in page counted as an app and woke beefy 2 s later (now: any browser sub-resource is a
  no-wake request).

## What didn't / what I learned

- **jellyfin-web logs the user out on any failure of `GET /System/Info`** (503, 5xx, network),
  and saves the wiped token. That client is behind the browser, the **LG webOS** and
  **Samsung Tizen** TV apps. This was already the case before tonight (an instant 503 did the
  same), but serving the cached server identity to such a client would have made it worse
  (it would get past its connect check and then be logged out). **Fix applied:** the cached
  identity is served only to clients that send an `Authorization: MediaBrowser` header
  (the native Android TV / Fire TV / Swiftfin apps). Web-based clients opened while beefy
  sleeps get "Server unavailable" and keep their login.
- Native apps are forgiving: Android TV keeps its token on a failed start (shows the user
  list; a tap retries), Swiftfin makes no network call before its home screen.
- My Playwright script failed three times before the browser test passed — Authentik shows
  username, password and TOTP on separate screens and the script typed into the wrong one.
  Test-tooling only; nothing in production was affected.
- The 18 s stages cannot reach beefy's ~50 s boot on their own: with stage 1 + stage 2 as
  built, a native app shows its spinner ~36 s, then one "connection failed", and its first
  retry succeeds. That is the honest state today.

## Next steps (proposal, not implemented)

`docs/superpowers/specs/2026-10-14-jellyfin-stage2-cached-home-proposal.md`: put a standard
**nginx caching proxy with `proxy_cache_use_stale`** between Traefik and Jellyfin for the
read-only start-up calls (per-user cache keyed by the app's `Authorization` header; shared
cache for `/web/*` assets and posters). nginx's 18 s connect timeout gives the staged waiting
for free, and `/System/Info` is replayed from cache so web clients are never logged out.
Expected result: open the app while beefy sleeps → within 18 s the last-seen home screen with
posters → by the time something is picked (~50 s) beefy is up. Limit: each user must have
opened the app once while beefy was up. The waker's `/jf/public-info` would be retired.

## Decisions / manual work needed from you

1. **Finish Jellyfin's setup wizard on the LAN** (`http://192.168.1.102:8096`). Until then the
   public hostname stays closed (403) and no app can be tested against it. Afterwards tell me:
   I remove the temporary `jellyfin-deny-all` from **both** routers and verify
   `/System/Info/Public` → 200 and `/Environment/Drives` → 401.
2. **Stage 2: build the nginx stale-cache proxy, or stop at stage 1?** (see the proposal).
3. **Push** the local commits? (25 unpushed on `main`, all from these two days.)
4. **Real-device check** once Jellyfin is open: open the TV/phone app while beefy sleeps and
   tell me what you see; the `observe` log will show exactly what each client sent.
5. Optional: the `BeefyWakeLoop` alert probably fired overnight (dozens of test boots) — it's
   expected and will clear on its own.
