# Wake page: state view + manual wake (split from auto-wake) — 2026-06-26

## Problem

The manual wake page at `/` **auto-fires a WoL packet on every visit** and drops
straight into a countdown. That means you can't just *look* at beefy's state
without also waking it, and a stray visit/prefetch wakes the box.

## Goal

- **`/` (root):** show beefy's current state and a big **Wake** button. Do **not**
  auto-fire WoL on load.
- **`/wol`:** keep today's behavior — auto-fire WoL on visit, countdown, poll until up.

## Behavior

### `/` — state + manual wake
- On load, show a brief **checking…** state, then resolve via `/status` to:
  - **asleep** (`up:false`): "beefy is asleep 😴" + a large **Wake beefy** button.
  - **up** (`up:true`): green "beefy is up and running ✅", **no button**.
- Poll `/status` every 3 s and live-update the view (asleep ↔ up) when not waking.
- Clicking **Wake**: POST `/wake`, switch to the **waking** countdown view, keep
  polling until `up:true` → "up and running".

### `/wol` — auto-wake (unchanged behavior)
- On load: POST `/wake` immediately, show countdown, poll until up.

### Both
- The collapsed **beefy history** panel stays at the bottom (lazy-fetch `/history`).

## Implementation

- One HTML/JS template served at both `/` and `/wol`. The server injects a JS flag
  `AUTOWAKE` (`false` for `/`, `true` for `/wol`) using the same `__PLACEHOLDER__`
  substitution already used for `__COUNTDOWN__`.
- JS becomes a small state machine with views: `#checking`, `#asleep` (button),
  `#waiting` (countdown), `#done` (up). One shared 3 s poll loop drives transitions;
  `startWaking()` is shared by the button click and the `/wol` auto path.
- Routing: add `/wol` → page with `autowake=true`; `/` → page with `autowake=false`.
- **No Traefik change** (router matches on Host; all paths pass through). **No backend
  endpoint changes** — `/wake` (POST-only), `/status`, `/history` reused as-is.

## Testing

`app/test_waker.py` (new; stdlib `unittest` + a throwaway `ThreadingHTTPServer`):
- `GET /` → 200, body carries `AUTOWAKE = false` and the Wake button.
- `GET /wol` → 200, body carries `AUTOWAKE = true`.
- `GET /wake` → 405 (POST-only guard preserved).
- `GET /status` → 200 JSON with an `up` key.
- unknown path → 404.

The client-side state machine (asleep/up/waking transitions) is verified by loading
the rendered page in a browser, since it's browser-only behavior.

## Out of scope

No change to the forwardAuth gate (`/gate`), the WoL/probe logic, or the history key.
