# Jellyfin cold start: cached server info + held requests — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While beefy boots, Jellyfin apps get the server's cached identity at once and their API requests are held (≤ 25 s) until Jellyfin is healthy, instead of an instant 503.

**Architecture:** All logic lives in the stdlib Beefy-Waker (`app/waker.py`). The gate's `policy=jellyfin` branch gains a bounded hold; a new `/jf/public-info` endpoint relays/caches `GET /System/Info/Public`. Traefik routes that one path to the waker. Spec: `docs/superpowers/specs/2026-10-14-jellyfin-cold-start-hold-design.md`.

**Tech Stack:** Python 3.13 stdlib (`http.server`, `urllib.request`, `threading`, `unittest`), Traefik v3 file provider.

**Conventions:** commit messages `Beefy-Waker: …` / `Traefik: …`, NO AI co-author trailer; `/home/pi/Projects` is a shared mono-repo on `main` — `git add` only the files you touched, never `git add -A`, never `git reset --hard`. Tests: `cd /home/pi/Projects/Docker/Beefy-Waker/app && python3 -m unittest -v test_waker`. Do not deploy/restart containers in Tasks 1–2 (the controller does that).

Existing code to know (v1.2.1): `is_jellyfin_ready(host, port)` (HTTP `/health`, 5 s positive cache via `_ready_until`), `wake()`, `wake_in_progress()`, `is_up()`, `is_browser_navigation(headers)`, `observe_record(headers, up, decision)`, `_forwarded_path_query(headers)`, `Handler._gate` → `_gate_jellyfin(up, port)`, `Handler._wake_and_wait_page(port)`, `WAKING_PAGE`, `SIGNIN_PAGE`, `JELLYFIN_PORT`, `PROBE_HOST`, `PROBE_PORT`. Tests already patch `is_up`, `is_jellyfin_ready`, `send_wol`, `_wake_campaign`, `sys.stdout`.

---

### Task 1: Bounded hold in the Jellyfin gate

**Files:** Modify `Docker/Beefy-Waker/app/waker.py`; Test `Docker/Beefy-Waker/app/test_waker.py`

- [ ] **Step 1: failing tests** — append to `test_waker.py` (above `if __name__` if present):

```python
class JellyfinHoldTest(unittest.TestCase):
    """policy=jellyfin holds non-browser requests until Jellyfin is healthy (bounded)."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), waker.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        waker._campaign_running = False
        self.out = io.StringIO()
        mock.patch("sys.stdout", self.out).start()
        self.send_wol = mock.patch.object(waker, "send_wol").start()
        mock.patch.object(waker, "_wake_campaign").start()
        mock.patch.object(waker, "is_up", return_value=False).start()
        mock.patch.object(waker, "HOLD_POLL_SECONDS", 0.05).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(setattr, waker, "_campaign_running", False)

    APP = {"Accept": "application/json", "X-Forwarded-Uri": "/System/Info",
           "Authorization": 'MediaBrowser Client="Android TV", Token="S"'}
    BROWSER = {"Accept": "text/html,*/*", "X-Forwarded-Uri": "/web/"}

    def gate(self, headers):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/gate?port=8096&policy=jellyfin", headers=headers)
        r = c.getresponse(); body = r.read().decode(); c.close()
        return r.status, body

    def observed(self):
        return [json.loads(l.split("observe ", 1)[1])
                for l in self.out.getvalue().splitlines() if " observe " in l]

    def test_app_request_is_held_then_passes_when_ready(self):
        ready = iter([False, False, False, True] + [True] * 50)
        with mock.patch.object(waker, "is_jellyfin_ready", side_effect=lambda h, p: next(ready)), \
             mock.patch.object(waker, "HOLD_SECONDS", 2):
            status, _ = self.gate(self.APP)
        self.assertEqual(status, 200)
        self.send_wol.assert_called_once()          # it still woke beefy first
        (rec,) = self.observed()
        self.assertEqual(rec["decision"], "wake")
        self.assertGreater(rec["held"], 0)

    def test_app_request_held_to_limit_then_503(self):
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=False), \
             mock.patch.object(waker, "HOLD_SECONDS", 0.3):
            t0 = time.monotonic()
            status, body = self.gate(self.APP)
            dt = time.monotonic() - t0
        self.assertEqual(status, 503)
        self.assertIn("Waking up beefy", body)
        self.assertGreaterEqual(dt, 0.3)
        self.assertLess(dt, 2)

    def test_starting_is_held_too_without_new_wake(self):
        waker._campaign_running = True
        ready = iter([False, False, True] + [True] * 50)
        with mock.patch.object(waker, "is_jellyfin_ready", side_effect=lambda h, p: next(ready)), \
             mock.patch.object(waker, "HOLD_SECONDS", 2):
            status, _ = self.gate(self.APP)
        self.assertEqual(status, 200)
        self.send_wol.assert_not_called()
        self.assertEqual(self.observed()[0]["decision"], "starting")

    def test_browser_is_not_held(self):
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=False), \
             mock.patch.object(waker, "HOLD_SECONDS", 5):
            t0 = time.monotonic()
            status, body = self.gate(self.BROWSER)
            dt = time.monotonic() - t0
        self.assertEqual(status, 503)
        self.assertIn("Sign in", body)
        self.assertLess(dt, 1)
        self.assertEqual(self.observed()[0]["held"], 0)

    def test_no_free_slot_means_immediate_503(self):
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=False), \
             mock.patch.object(waker, "HOLD_SECONDS", 5), \
             mock.patch.object(waker, "_hold_slots", threading.BoundedSemaphore(0)):
            t0 = time.monotonic()
            status, _ = self.gate(self.APP)
            dt = time.monotonic() - t0
        self.assertEqual(status, 503)
        self.assertLess(dt, 1)
        self.assertEqual(self.observed()[0]["held"], 0)

    def test_hold_seconds_is_clamped_below_traefik_timeout(self):
        self.assertLessEqual(waker.HOLD_SECONDS, 28)
```

Add `import time` to the test imports if missing.

- [ ] **Step 2:** run tests, confirm the new ones FAIL (no `HOLD_SECONDS`, no `held` field).

- [ ] **Step 3: implement** in `waker.py`:

3a. Config, after the `READY_CACHE_SECONDS` block:

```python
# Hold a Jellyfin app's request while beefy boots instead of answering 503 at
# once. The limit must stay under Traefik's forwardAuth client timeout (a fixed
# 30 s in pkg/middlewares/auth/forward.go) and the Android TV app's 30 s request
# timeout. A cold boot takes ~50 s, so a single hold cannot bridge it: the point
# is that the app shows its own spinner, and its first retry then succeeds.
HOLD_SECONDS = min(float(os.environ.get("HOLD_SECONDS", "25")), 28.0)
HOLD_SLOTS = int(os.environ.get("HOLD_SLOTS", "16"))   # concurrent held requests
HOLD_POLL_SECONDS = 1.0
_hold_slots = threading.BoundedSemaphore(HOLD_SLOTS)


def hold_until_ready(host, port, limit):
    """Wait up to `limit` s for Jellyfin to be healthy. Returns (ready, seconds_held).

    Non-blocking on the slot: with every slot busy (scanners while beefy sleeps)
    the caller falls back to answering immediately.
    """
    if not _hold_slots.acquire(blocking=False):
        return False, 0.0
    t0 = time.monotonic()
    try:
        while True:
            if is_jellyfin_ready(host, port):
                return True, time.monotonic() - t0
            if time.monotonic() - t0 >= limit:
                return False, time.monotonic() - t0
            time.sleep(HOLD_POLL_SECONDS)
    finally:
        _hold_slots.release()
```

3b. Extract the decision from `_gate_jellyfin` into a module function (same rules), so Task 2 can reuse it:

```python
def jellyfin_decision(up, headers):
    if up:
        return "pass"
    if wake_in_progress() or is_up(PROBE_HOST, PROBE_PORT):
        return "starting"
    if is_browser_navigation(headers):
        return "signin"
    return "wake"
```

3c. Rewrite `_gate_jellyfin(self, up, port)`:

```python
    def _gate_jellyfin(self, up, port):
        # Jellyfin has no Authentik in front (native apps can't follow a login
        # redirect), so this is the only place anonymous wakes can be refused.
        # Browsers are refused and sent to the signed-in wake page; everything
        # else still wakes (until the observe log shows a safe rule for apps),
        # and is then HELD until Jellyfin is healthy (bounded) so the app sees a
        # slow server rather than an instant failure.
        decision = jellyfin_decision(up, self.headers)
        held = 0.0
        if decision == "wake":
            try:
                wake()
                self.log_message("beefy down (%s:%d) - sent WoL to %s via %s",
                                 PROBE_HOST, port, MAC, BROADCAST)
            except Exception as e:
                self.log_message("WoL send failed: %s", e)
        if decision in ("wake", "starting"):
            ready, held = hold_until_ready(PROBE_HOST, port, HOLD_SECONDS)
            if ready:
                decision = "pass"
        fwd_path, _ = _forwarded_path_query(self.headers)
        if not up or "/" + fwd_path.lstrip("/").lower() == "/system/info/public":
            rec = observe_record(self.headers, up, decision)
            rec["held"] = round(held, 1)
            self.log_message("observe %s", json.dumps(rec, sort_keys=True))
        if decision == "pass":
            self._send(200, "text/plain", b"")
        elif decision == "signin":
            self._send(503, "text/html; charset=utf-8", SIGNIN_PAGE)
        else:
            self._send(503, "text/html; charset=utf-8", WAKING_PAGE, retry_after=5)
```

(`_wake_and_wait_page` stays for the non-policy path.)

3d. Docstring: under the `/gate` line add `HOLD_SECONDS  hold app requests up to this (≤28) default 25` and `HOLD_SLOTS  concurrent holds  default 16` to the env list.

- [ ] **Step 4:** run all tests → PASS (existing 40 + 6 new).
- [ ] **Step 5:** commit: `git add Docker/Beefy-Waker/app/waker.py Docker/Beefy-Waker/app/test_waker.py && git commit -m "Beefy-Waker: hold Jellyfin app requests while beefy boots"`

---

### Task 2: `/jf/public-info` — relay and cache `/System/Info/Public`

**Files:** Modify `Docker/Beefy-Waker/app/waker.py`, `app/test_waker.py`, `app/VERSION` (→ `1.3.0`), `README.md`

- [ ] **Step 1: failing tests** — append:

```python
class PublicInfoTest(unittest.TestCase):
    """/jf/public-info relays Jellyfin's /System/Info/Public and serves it from cache while down."""

    class Stub(http.server.BaseHTTPRequestHandler):
        body = b'{"Id":"abc123","Version":"12.1.0","ProductName":"Jellyfin Server"}'
        def do_GET(self):
            if self.path == "/System/Info/Public":
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(self.body))); self.end_headers()
                self.wfile.write(self.body)
            else:
                self.send_error(404)
        def log_message(self, *a): pass

    @classmethod
    def setUpClass(cls):
        cls.jf = ThreadingHTTPServer(("127.0.0.1", 0), cls.Stub)
        threading.Thread(target=cls.jf.serve_forever, daemon=True).start()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), waker.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for s in (cls.srv, cls.jf):
            s.shutdown(); s.server_close()

    def setUp(self):
        waker._campaign_running = False
        waker._public_info = None
        self.cache = tempfile.NamedTemporaryFile(delete=False); self.cache.close()
        os.unlink(self.cache.name)
        mock.patch.object(waker, "PUBLIC_INFO_CACHE", self.cache.name).start()
        mock.patch.object(waker, "PROBE_HOST", "127.0.0.1").start()
        mock.patch.object(waker, "JELLYFIN_PORT", self.jf.server_address[1]).start()
        self.out = io.StringIO(); mock.patch("sys.stdout", self.out).start()
        self.send_wol = mock.patch.object(waker, "send_wol").start()
        mock.patch.object(waker, "_wake_campaign").start()
        mock.patch.object(waker, "is_up", return_value=False).start()
        mock.patch.object(waker, "HOLD_POLL_SECONDS", 0.05).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(lambda: os.path.exists(self.cache.name) and os.unlink(self.cache.name))
        self.addCleanup(setattr, waker, "_public_info", None)

    APP = {"Accept": "application/json", "X-Forwarded-Uri": "/System/Info/Public",
           "Authorization": 'MediaBrowser Client="Android TV", Token="S"'}

    def req(self, headers):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/jf/public-info", headers=headers)
        r = c.getresponse(); body = r.read(); ctype = r.getheader("Content-Type"); c.close()
        return r.status, body, ctype

    def observed(self):
        return [json.loads(l.split("observe ", 1)[1])
                for l in self.out.getvalue().splitlines() if " observe " in l]

    def test_healthy_relays_and_caches(self):
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=True):
            status, body, ctype = self.req(self.APP)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["Id"], "abc123")
        self.assertIn("application/json", ctype)
        self.assertTrue(os.path.exists(self.cache.name))
        self.assertEqual(json.loads(open(self.cache.name).read())["Id"], "abc123")
        self.send_wol.assert_not_called()
        self.assertEqual(self.observed()[0]["decision"], "pass")
        self.assertFalse(self.observed()[0]["cached"])

    def test_down_with_cache_answers_at_once_and_wakes(self):
        waker._public_info = self.Stub.body
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=False), \
             mock.patch.object(waker, "HOLD_SECONDS", 5):
            t0 = time.monotonic()
            status, body, _ = self.req(self.APP)
            dt = time.monotonic() - t0
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["Id"], "abc123")
        self.assertLess(dt, 1)
        self.send_wol.assert_called_once()
        rec = self.observed()[0]
        self.assertEqual(rec["decision"], "wake"); self.assertTrue(rec["cached"])

    def test_down_without_cache_holds_then_relays(self):
        ready = iter([False, False, True] + [True] * 50)
        with mock.patch.object(waker, "is_jellyfin_ready", side_effect=lambda h, p: next(ready)), \
             mock.patch.object(waker, "HOLD_SECONDS", 2):
            status, body, _ = self.req(self.APP)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["Id"], "abc123")

    def test_down_without_cache_limit_reached_is_503(self):
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=False), \
             mock.patch.object(waker, "HOLD_SECONDS", 0.2):
            status, body, _ = self.req(self.APP)
        self.assertEqual(status, 503)
        self.assertIn(b"Waking up beefy", body)

    def test_browser_gets_signin_no_wake(self):
        waker._public_info = self.Stub.body
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=False):
            status, body, _ = self.req({"Accept": "text/html", "X-Forwarded-Uri": "/System/Info/Public"})
        self.assertEqual(status, 503)
        self.assertIn(b"Sign in", body)
        self.send_wol.assert_not_called()

    def test_cache_file_loaded_at_startup(self):
        with open(self.cache.name, "wb") as f:
            f.write(b'{"Id":"fromfile"}')
        waker._load_public_info()
        self.assertEqual(json.loads(waker._public_info)["Id"], "fromfile")
```

Add `import tempfile` to the test imports.

- [ ] **Step 2:** run → the new tests FAIL (404 / missing names).

- [ ] **Step 3: implement** in `waker.py`:

3a. After the hold block:

```python
# Cached answer to Jellyfin's `GET /System/Info/Public`, the first thing every
# app asks. Served while beefy sleeps so the app believes the server is there and
# shows its own loading state instead of "server unavailable". Memory + a file so
# a waker restart while beefy sleeps keeps it. Only 200 answers are cached.
PUBLIC_INFO_CACHE = os.environ.get("PUBLIC_INFO_CACHE", "/tmp/public-info.json")
_public_info = None
_public_info_lock = threading.Lock()


def _load_public_info():
    global _public_info
    try:
        with open(PUBLIC_INFO_CACHE, "rb") as f:
            data = f.read()
        json.loads(data)                      # must be valid JSON
        with _public_info_lock:
            _public_info = data
    except (OSError, ValueError):
        pass


def _store_public_info(data):
    global _public_info
    with _public_info_lock:
        _public_info = data
    try:
        with open(PUBLIC_INFO_CACHE, "wb") as f:
            f.write(data)
    except OSError:
        pass


def fetch_public_info(host, port):
    """Relay Jellyfin's /System/Info/Public; returns bytes or None."""
    try:
        with urllib.request.urlopen("http://%s:%d/System/Info/Public" % (host, port),
                                    timeout=3) as r:
            data = r.read(65536)
            if r.status == 200:
                json.loads(data)
                _store_public_info(data)
                return data
    except (OSError, ValueError):
        pass
    return None
```

3b. Route: in `_route`, before `else: self.send_error(404)`: `elif path == "/jf/public-info": self._jf_public_info()`.

3c. Handler method (next to `_jf_page`):

```python
    def _jf_public_info(self):
        # GET /System/Info/Public on the Jellyfin hostname is routed here (Traefik
        # replacePathRegex). Healthy: relay + cache. Down: same decision as the
        # gate; apps get the cached identity at once, browsers the sign-in page.
        up = is_jellyfin_ready(PROBE_HOST, JELLYFIN_PORT)
        decision = jellyfin_decision(up, self.headers)
        held, cached, body = 0.0, False, None
        if decision == "pass":
            body = fetch_public_info(PROBE_HOST, JELLYFIN_PORT)
        elif decision != "signin":
            if decision == "wake":
                try:
                    wake()
                    self.log_message("beefy down (%s:%d) - sent WoL to %s via %s",
                                     PROBE_HOST, JELLYFIN_PORT, MAC, BROADCAST)
                except Exception as e:
                    self.log_message("WoL send failed: %s", e)
            with _public_info_lock:
                body = _public_info
            if body is not None:
                cached = True
            else:
                ready, held = hold_until_ready(PROBE_HOST, JELLYFIN_PORT, HOLD_SECONDS)
                if ready:
                    body = fetch_public_info(PROBE_HOST, JELLYFIN_PORT)
        rec = observe_record(self.headers, up, decision)
        rec["held"] = round(held, 1)
        rec["cached"] = cached
        self.log_message("observe %s", json.dumps(rec, sort_keys=True))
        if decision == "signin":
            self._send(503, "text/html; charset=utf-8", SIGNIN_PAGE)
        elif body is not None:
            self._send(200, "application/json", body)
        else:
            self._send(503, "text/html; charset=utf-8", WAKING_PAGE, retry_after=5)
```

3d. In `main()`, before `srv = ...`: `_load_public_info()`.

3e. Docstring endpoint list: `GET /jf/public-info  relay/cache of Jellyfin's /System/Info/Public (apps' connect check)`; env `PUBLIC_INFO_CACHE  default /tmp/public-info.json`. `app/VERSION` → `1.3.0`; README "Versions" line → `v1.3.0`; README Jellyfin section: add a short "Cold start (v1.3.0)" paragraph: cached identity + bounded hold (≤ 25 s, Traefik's forwardAuth limit is 30 s), expected UX (spinner → one retry succeeds), `observe` fields `held`/`cached`.

- [ ] **Step 4:** run all tests → PASS.
- [ ] **Step 5:** commit: `git add Docker/Beefy-Waker/app/waker.py Docker/Beefy-Waker/app/test_waker.py Docker/Beefy-Waker/app/VERSION Docker/Beefy-Waker/README.md && git commit -m "Beefy-Waker: cached /System/Info/Public for Jellyfin apps, v1.3.0"`

---

### Task 3 (controller): deploy + Traefik route + live tests

- [ ] `docker restart beefy-waker`, wait healthy, `curl -s http://192.168.1.2:9001/jf/ | grep v1.3.0`.
- [ ] `dynamic/jellyfin.yml`: add router `jellyfin-public-info` (priority 25, `Path(`/System/Info/Public`)`, service `beefy-waker-jf`, middlewares `jellyfin-deny-all`, `jellyfin-public-info-rewrite`, `jellyfin-secure-headers`) + middleware `jellyfin-public-info-rewrite` (`replacePathRegex` `^/System/Info/Public$` → `/jf/public-info`). Commit `Traefik: route Jellyfin's /System/Info/Public to the waker cache`.
- [ ] Temporary LAN test file `jellyfin-test.yml` with the same three routers minus `jellyfin-deny-all`; delete after.
- [ ] Live test while beefy is asleep (curl, Android-TV-like headers): `/System/Info/Public` → 200 cached JSON in < 2 s and a WoL in the waker log; `/System/Info` → held ~25 s → 503; repeat `/System/Info` → 200 once healthy. Browser Playwright flow with throwaway Authentik user.
