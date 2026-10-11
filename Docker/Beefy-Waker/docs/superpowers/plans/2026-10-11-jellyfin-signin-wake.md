# Jellyfin sign-in-to-wake + client-header observation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Browsers can no longer wake beefy anonymously via `jellyfin.holy-grail.ch` (they sign in through Authentik first, then get a booting page); every other Jellyfin request keeps waking beefy as today while the gate logs a redacted fingerprint of it.

**Architecture:** All decision logic lives in the existing stdlib Beefy-Waker (`app/waker.py`), activated only when Traefik calls the gate with `policy=jellyfin`. The booting page is a new `/jf/*` endpoint family on the same waker, published by a new Traefik router behind Authentik forward auth with a path rewrite. Spec: `docs/superpowers/specs/2026-10-11-jellyfin-signin-wake-design.md`.

**Tech Stack:** Python 3.13 stdlib (`http.server`, `unittest`), Traefik v3 file provider, Authentik 2026.5 (embedded outpost, `ak shell`).

**Conventions:** commit messages `Beefy-Waker: …` / `Traefik: …`, NO AI co-author trailer. Repo is the shared `/home/pi/Projects` mono-repo on `main` — `git add` only the files you touched, never `git add -A`, never `git reset --hard`. Run tests with:
`cd /home/pi/Projects/Docker/Beefy-Waker/app && python3 -m unittest -v test_waker`

---

## File map

- `Docker/Beefy-Waker/app/waker.py` — gate policy, observation log, `/jf/*` endpoints, new page templates.
- `Docker/Beefy-Waker/app/test_waker.py` — new test classes (existing ones untouched).
- `Docker/Beefy-Waker/app/VERSION` — `1.1.0` → `1.2.0`.
- `Docker/Beefy-Waker/README.md` — document policy, observe log, `/jf`.
- `Docker/Traefik/traefik/dynamic/jellyfin.yml` — outpost + wake-page routers, rewrite middleware, `&policy=jellyfin`.
- `Docker/Traefik/docs/2026-10-06-authentik-sso.md` — record the new Authentik objects.

---

### Task 1: Gate `policy=jellyfin` decisions + observation log

**Files:** Modify `Docker/Beefy-Waker/app/waker.py`; Test `Docker/Beefy-Waker/app/test_waker.py`

- [ ] **Step 1: Write the failing tests** — append to `test_waker.py` (above the `if __name__` block if there is one, else at the end):

```python
import io
import json
from unittest import mock


class JellyfinGateTest(unittest.TestCase):
    """Gate with policy=jellyfin. is_up/send_wol are patched: no packets, no probes."""

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
        p_out = mock.patch("sys.stdout", self.out)
        p_wol = mock.patch.object(waker, "send_wol")
        p_camp = mock.patch.object(waker, "_wake_campaign")   # no background thread
        self.send_wol = p_wol.start()
        p_out.start(); p_camp.start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(setattr, waker, "_campaign_running", False)

    def gate(self, up, headers, policy="jellyfin"):
        with mock.patch.object(waker, "is_up", return_value=up):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            q = "/gate?port=8096" + ("&policy=" + policy if policy else "")
            c.request("GET", q, headers=headers)
            r = c.getresponse()
            body = r.read().decode()
            c.close()
        return r.status, body

    def observed(self):
        return [json.loads(l.split("observe ", 1)[1])
                for l in self.out.getvalue().splitlines() if " observe " in l]

    BROWSER = {"Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
               "X-Forwarded-Uri": "/web/", "User-Agent": "Mozilla/5.0 Test"}
    APP = {"Accept": "application/json",
           "X-Forwarded-Uri": "/System/Info/Public",
           "Authorization": 'MediaBrowser Client="Android TV", Device="x", '
                            'DeviceId="d", Version="0.18", Token="SECRET123"'}

    def test_up_passes_through(self):
        status, _ = self.gate(True, self.BROWSER)
        self.assertEqual(status, 200)
        self.send_wol.assert_not_called()

    def test_down_browser_gets_signin_page_and_no_wake(self):
        status, body = self.gate(False, self.BROWSER)
        self.assertEqual(status, 503)
        self.assertIn("/beefy-wake/", body)
        self.assertIn("Sign in", body)
        self.send_wol.assert_not_called()

    def test_down_app_still_wakes(self):
        status, body = self.gate(False, self.APP)
        self.assertEqual(status, 503)
        self.assertIn("Waking up beefy", body)
        self.send_wol.assert_called_once()

    def test_down_scanner_without_accept_still_wakes(self):
        status, _ = self.gate(False, {"X-Forwarded-Uri": "/.env"})
        self.assertEqual(status, 503)
        self.send_wol.assert_called_once()

    def test_down_wake_in_progress_browser_gets_starting_page_no_new_wake(self):
        waker._campaign_running = True
        status, body = self.gate(False, self.BROWSER)
        self.assertEqual(status, 503)
        self.assertIn("Waking up beefy", body)
        self.send_wol.assert_not_called()

    def test_without_policy_browser_still_wakes_as_before(self):
        status, body = self.gate(False, self.BROWSER, policy=None)
        self.assertEqual(status, 503)
        self.assertIn("Waking up beefy", body)
        self.send_wol.assert_called_once()

    def test_observe_logged_when_down_with_fields(self):
        self.gate(False, self.APP)
        (rec,) = self.observed()
        self.assertEqual(rec["decision"], "wake")
        self.assertFalse(rec["up"])
        self.assertTrue(rec["auth_mediabrowser"])
        self.assertEqual(rec["client"], "Android TV")
        self.assertEqual(rec["path"], "/System/Info/Public")
        self.assertEqual(rec["accept"], "application/json")

    def test_observe_logged_when_up_only_for_system_info_public(self):
        self.gate(True, self.APP)
        self.gate(True, dict(self.BROWSER))           # /web/ while up: not logged
        recs = self.observed()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["decision"], "pass")

    def test_observe_path_match_is_case_insensitive(self):
        self.gate(True, {"X-Forwarded-Uri": "/system/info/public"})
        self.assertEqual(len(self.observed()), 1)

    def test_observe_never_logs_tokens_or_query_values(self):
        h = dict(self.APP)
        h["X-Forwarded-Uri"] = "/Items?api_key=QUERYSECRET&Limit=5"
        h["X-Emby-Token"] = "HEADERSECRET"
        self.gate(False, h)
        log = self.out.getvalue()
        for secret in ("SECRET123", "QUERYSECRET", "HEADERSECRET"):
            self.assertNotIn(secret, log)
        (rec,) = self.observed()
        self.assertEqual(rec["query_keys"], ["Limit", "api_key"])
        self.assertTrue(rec["x_emby_token"])

    def test_observe_not_logged_without_policy(self):
        self.gate(False, self.APP, policy=None)
        self.assertEqual(self.observed(), [])
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/pi/Projects/Docker/Beefy-Waker/app && python3 -m unittest -v test_waker 2>&1 | tail -15`
Expected: the new `JellyfinGateTest` tests FAIL/ERROR (e.g. no sign-in page, no `observe` lines); the pre-existing tests still pass.

- [ ] **Step 3: Implement** in `waker.py`:

3a. Add `import re` to the imports (alphabetical, after `import os`).

3b. After the `PROBE_TIMEOUT = 1.0` line add:

```python
# Public URL prefix of the signed-in wake page (Traefik rewrites it to /jf/).
PUBLIC_WAKE_PREFIX = "/beefy-wake"
JELLYFIN_PORT = int(os.environ.get("JELLYFIN_PORT", "8096"))
_CLIENT_RE = re.compile(r'Client="([^"]*)"')
```

3c. After `WAKING_PAGE` add the sign-in page (served by the gate as a 503 body, so Traefik relays it to the browser):

```python
# Shown by the gate (policy=jellyfin) to a BROWSER while beefy is asleep. It does
# NOT wake beefy: anonymous page loads were how internet scanners kept booting it.
# The button goes to the Authentik-protected wake page instead.
SIGNIN_PAGE = b"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jellyfin is asleep</title>
<style>
  html,body{height:100%;margin:0}
  body{display:flex;align-items:center;justify-content:center;
       font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3}
  .card{text-align:center;max-width:28rem;padding:2rem}
  .moon{font-size:3rem;line-height:1;margin:0 auto 1rem}
  h1{font-size:1.3rem;margin:.5rem 0}
  p{color:#8b949e;margin:.25rem 0}
  .btn{display:inline-block;text-decoration:none;font-weight:600;font-size:1.2rem;
       padding:.9rem 2.2rem;margin:1.2rem 0 .4rem;border-radius:.7rem;
       background:#238636;color:#fff}
  .btn:hover{background:#2ea043}
</style></head>
<body><div class="card">
  <div class="moon">&#128164;</div>
  <h1>Jellyfin is asleep</h1>
  <p>The media server sleeps to save power.</p>
  <a class="btn" href="/beefy-wake/">Sign in to start it</a>
  <p>It takes about a minute to start after you sign in.</p>
</div></body></html>"""
```

3d. After the `wake()` function add:

```python
def wake_in_progress():
    with _campaign_lock:
        return _campaign_running


def is_browser_navigation(headers):
    """A browser page load. Browsers send Accept: text/html on navigation;
    Jellyfin API calls send application/json and image loaders image/* or */*."""
    return "text/html" in (headers.get("Accept") or "").lower()


def observe_record(headers, up, decision):
    """Redacted fingerprint of a Jellyfin request, used to design the app rule.

    Never includes a token or a query VALUE: the MediaBrowser header carries
    Token="...", and api_key/ApiKey query values are tokens.
    """
    fwd = urlparse(headers.get("X-Forwarded-Uri") or "/")
    auth = headers.get("Authorization") or ""
    mb = auth.strip().lower().startswith("mediabrowser")
    emby_auth = headers.get("X-Emby-Authorization") or ""
    m = _CLIENT_RE.search(auth if mb else emby_auth)
    return {
        "up": up,
        "decision": decision,
        "method": headers.get("X-Forwarded-Method") or "",
        "path": fwd.path[:200],
        "query_keys": sorted(parse_qs(fwd.query, keep_blank_values=True)),
        "auth_mediabrowser": mb,
        "x_emby_authorization": bool(emby_auth),
        "x_emby_token": bool(headers.get("X-Emby-Token")),
        "x_mediabrowser_token": bool(headers.get("X-MediaBrowser-Token")),
        "client": m.group(1)[:40] if m else "",
        "ua": (headers.get("User-Agent") or "")[:160],
        "accept": (headers.get("Accept") or "")[:80],
        "sec_fetch_mode": (headers.get("Sec-Fetch-Mode") or "")[:20],
        "ip": (headers.get("X-Forwarded-For") or "").split(",")[0].strip()[:45],
    }
```

3e. In `Handler._gate`, replace everything from `if is_up(PROBE_HOST, port):` to the end of the method with:

```python
        up = is_up(PROBE_HOST, port)
        if q.get("policy", [""])[0] == "jellyfin":
            self._gate_jellyfin(up)
            return
        if up:
            self._send(200, "text/plain", b"")
            return
        self._wake_and_wait_page(port)

    def _wake_and_wait_page(self, port):
        try:
            wake()
            self.log_message("beefy down (%s:%d) - sent WoL to %s via %s",
                             PROBE_HOST, port, MAC, BROADCAST)
        except Exception as e:
            self.log_message("WoL send failed: %s", e)
        self._send(503, "text/html; charset=utf-8", WAKING_PAGE, retry_after=5)

    def _gate_jellyfin(self, up):
        # Jellyfin has no Authentik in front (native apps can't follow a login
        # redirect), so this is the only place anonymous wakes can be refused.
        # Browsers are refused and sent to the signed-in wake page; everything
        # else still wakes (until the observe log shows a safe rule for apps).
        if up:
            decision = "pass"
        elif wake_in_progress():
            decision = "starting"
        elif is_browser_navigation(self.headers):
            decision = "signin"
        else:
            decision = "wake"
        fwd_path = urlparse(self.headers.get("X-Forwarded-Uri") or "/").path
        if not up or fwd_path.lower() == "/system/info/public":
            self.log_message("observe %s", json.dumps(
                observe_record(self.headers, up, decision), sort_keys=True))
        if decision == "pass":
            self._send(200, "text/plain", b"")
        elif decision == "starting":
            self._send(503, "text/html; charset=utf-8", WAKING_PAGE, retry_after=5)
        elif decision == "signin":
            self._send(503, "text/html; charset=utf-8", SIGNIN_PAGE)
        else:
            self._wake_and_wait_page(JELLYFIN_PORT)
```

- [ ] **Step 4: Run the tests**

Run: `cd /home/pi/Projects/Docker/Beefy-Waker/app && python3 -m unittest -v test_waker 2>&1 | tail -15`
Expected: all tests (old + new) PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/pi/Projects
git add Docker/Beefy-Waker/app/waker.py Docker/Beefy-Waker/app/test_waker.py
git commit -m "Beefy-Waker: Jellyfin gate policy - browsers sign in to wake, log client headers"
```

---

### Task 2: Signed-in booting page `/jf/*`, version, README

**Files:** Modify `Docker/Beefy-Waker/app/waker.py`, `app/test_waker.py`, `app/VERSION`, `README.md`

- [ ] **Step 1: Write the failing tests** — append to `test_waker.py`:

```python
class JellyfinWakePageTest(unittest.TestCase):
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
        mock.patch("sys.stdout", io.StringIO()).start()
        self.send_wol = mock.patch.object(waker, "send_wol").start()
        mock.patch.object(waker, "_wake_campaign").start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(setattr, waker, "_campaign_running", False)

    def req(self, method, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path)
        r = c.getresponse()
        body = r.read().decode()
        c.close()
        return r.status, body

    def test_page_served_at_jf_with_and_without_slash(self):
        for p in ("/jf", "/jf/"):
            status, body = self.req("GET", p)
            self.assertEqual(status, 200, p)
            self.assertIn("/beefy-wake/wake", body)
            self.assertIn("/beefy-wake/status", body)
            self.assertIn("/web/", body)
            self.assertNotIn("/history", body)      # no admin panel on the public page

    def test_status_probes_jellyfin_port(self):
        with mock.patch.object(waker, "is_up", return_value=True) as up:
            status, body = self.req("GET", "/jf/status")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"up": True})
        up.assert_called_once_with(waker.PROBE_HOST, waker.JELLYFIN_PORT)

    def test_wake_is_post_only(self):
        status, _ = self.req("GET", "/jf/wake")
        self.assertEqual(status, 405)
        self.send_wol.assert_not_called()
        status, body = self.req("POST", "/jf/wake")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"sent": True})
        self.send_wol.assert_called_once()

    def test_admin_endpoints_not_reachable_under_jf(self):
        for p in ("/jf/history", "/jf/gate", "/jf/wol", "/jf/anything"):
            status, _ = self.req("GET", p)
            self.assertEqual(status, 404, p)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/pi/Projects/Docker/Beefy-Waker/app && python3 -m unittest -v test_waker 2>&1 | tail -15`
Expected: `JellyfinWakePageTest` tests FAIL (404s).

- [ ] **Step 3: Implement** in `waker.py`:

3a. After `SIGNIN_PAGE` add the booting page (`__COUNTDOWN__`/`__VERSION__` substituted at serve time; absolute `/beefy-wake/...` URLs so it works whether or not the visitor typed the trailing slash):

```python
# Public booting page, reached at https://jellyfin.holy-grail.ch/beefy-wake/ AFTER
# an Authentik login (Traefik rewrites /beefy-wake/* to /jf/*). Fires the wake on
# load, counts down, and hands over to Jellyfin as soon as port 8096 answers.
# Deliberately no history panel and no links to the LAN admin page.
JF_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Starting Jellyfin</title>
<style>
  html,body{height:100%;margin:0}
  body{display:flex;align-items:center;justify-content:center;
       font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3}
  .card{text-align:center;max-width:30rem;padding:2rem}
  .spin{width:3.5rem;height:3.5rem;margin:0 auto 1.5rem;border:4px solid #30363d;
        border-top-color:#58a6ff;border-radius:50%;animation:s 1s linear infinite}
  @keyframes s{to{transform:rotate(360deg)}}
  h1{font-size:1.4rem;margin:.4rem 0}
  p{color:#8b949e;margin:.3rem 0}
  .count{font-size:2.6rem;font-variant-numeric:tabular-nums;margin:.4rem 0;color:#58a6ff}
  .ver{margin-top:1.4rem;color:#484f58;font-size:.75rem}
</style></head>
<body><div class="card">
  <div class="spin"></div>
  <h1 id="title">Starting Jellyfin&hellip;</h1>
  <div class="count" id="count">~__COUNTDOWN__s</div>
  <p id="sub">The media server is booting. You will be taken to Jellyfin automatically.</p>
  <div class="ver">v__VERSION__</div>
<script>
const BASE = '/beefy-wake/';
let left = __COUNTDOWN__;
const countEl = document.getElementById('count');
const subEl = document.getElementById('sub');
function tick(){
  left -= 1;
  if(left > 0){ countEl.textContent = '~' + left + 's'; }
  else {
    countEl.textContent = 'almost\\u2026';
    subEl.textContent = 'Taking a little longer than usual, still trying\\u2026';
  }
}
async function isUp(){
  try{ return (await (await fetch(BASE + 'status', {cache:'no-store'})).json()).up; }
  catch(e){ return false; }
}
async function poll(){
  if(await isUp()){
    document.getElementById('title').textContent = 'Jellyfin is ready';
    location.replace('/web/');
    return;
  }
  setTimeout(poll, 2000);
}
(async () => {
  if(await isUp()){ location.replace('/web/'); return; }
  fetch(BASE + 'wake', {method:'POST'}).catch(()=>{});
  setInterval(tick, 1000);
  setTimeout(poll, 2000);
})();
</script>
</div></body></html>"""
```

3b. In `Handler._route`, before the final `else: self.send_error(404)`, add:

```python
        elif path == "/jf":
            self._jf_page()
        elif path == "/jf/status":
            up = is_up(PROBE_HOST, JELLYFIN_PORT)
            self._send(200, "application/json", json.dumps({"up": up}).encode())
        elif path == "/jf/wake":
            self._wake()
```

(`/jf/` becomes `/jf` via the existing `rstrip("/")`; every other `/jf/...` path falls through to 404.)

3c. Add the method next to `_page`:

```python
    def _jf_page(self):
        body = (JF_PAGE
                .replace("__COUNTDOWN__", str(COUNTDOWN))
                .replace("__VERSION__", VERSION)
                .encode())
        self._send(200, "text/html; charset=utf-8", body)
```

3d. Update the module docstring endpoint list: add
```
  GET  /jf/       public booting page (behind Authentik at /beefy-wake/)
  GET  /jf/status JSON {"up": ...} for Jellyfin's port (JELLYFIN_PORT, 8096)
  POST /jf/wake   same as /wake
```
and under the `/gate` line: `(?policy=jellyfin: browsers get a sign-in page instead of a wake; requests are logged as "observe {...}")`. Add `JELLYFIN_PORT  Jellyfin port for /jf/status  default 8096` to the env list.

3e. `app/VERSION`: change `1.1.0` to `1.2.0`.

3f. `README.md`: add a section `## Jellyfin: sign in to wake (v1.2.0)` summarising: gate `policy=jellyfin` table (pass / starting / signin / wake), that browsers no longer wake beefy anonymously, the public page `https://jellyfin.holy-grail.ch/beefy-wake/` behind Authentik group `streaming-users`, the `observe` log and how to read it:
`sudo grep -a '"observe ' "$(docker inspect -f '{{.LogPath}}' beefy-waker)" | tail` (plain `docker logs` is truncated by NUL bytes from the 2026-09-01 power cut), and that the app rule will be decided from that log. Link the spec.

- [ ] **Step 4: Run the tests**

Run: `cd /home/pi/Projects/Docker/Beefy-Waker/app && python3 -m unittest -v test_waker 2>&1 | tail -15`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/pi/Projects
git add Docker/Beefy-Waker/app/waker.py Docker/Beefy-Waker/app/test_waker.py Docker/Beefy-Waker/app/VERSION Docker/Beefy-Waker/README.md
git commit -m "Beefy-Waker: signed-in Jellyfin booting page at /jf, v1.2.0"
```

---

### Task 3: Deploy the waker (controller, live)

- [ ] `cd /home/pi/Projects/Docker/Beefy-Waker && docker restart beefy-waker` (script is bind-mounted; no rebuild).
- [ ] Wait healthy: `until [ "$(docker inspect -f '{{.State.Health.Status}}' beefy-waker)" = healthy ]; do sleep 2; done`
- [ ] Gate unchanged for other routes: `curl -s -o /dev/null -w '%{http_code}\n' 'http://192.168.1.2:9001/gate?port=22'` → `200` if beefy up, `503` if down.
- [ ] `curl -s http://192.168.1.2:9001/jf/ | grep -c beefy-wake` → ≥ 1.

### Task 4: Authentik objects (controller, `ak shell`)

- [ ] Inspect an existing forward-auth provider to copy its flows: `docker exec authentik-server ak shell -c "from authentik.providers.proxy.models import ProxyProvider; p=ProxyProvider.objects.get(name__icontains='radarr'); print(p.name, p.mode, p.external_host, p.authorization_flow.slug, p.invalidation_flow.slug if p.invalidation_flow else None)"`
- [ ] Create provider `jellyfin-wake` (same flows, `mode=forward_single`, `external_host=https://jellyfin.holy-grail.ch`), Application `jellyfin-wake` (name "Jellyfin wake", provider set), PolicyBinding group `streaming-users` order 0, and add the provider to the embedded outpost (`Outpost.objects.get(managed='goauthentik.io/outposts/embedded').providers.add(p)`).
- [ ] Verify by re-listing apps + bindings (same command as used in brainstorming).

### Task 5: Traefik routes (controller, live)

**Files:** Modify `Docker/Traefik/traefik/dynamic/jellyfin.yml`, `Docker/Traefik/docs/2026-10-06-authentik-sso.md`

- [ ] In `jellyfin.yml` `http.routers` add:

```yaml
    # Authentik outpost callback for the wake page below. No middlewares; must
    # beat the catch-all jellyfin router (priority 1).
    jellyfin-outpost:
      rule: "Host(`jellyfin.holy-grail.ch`) && PathPrefix(`/outpost.goauthentik.io/`)"
      entryPoints: ["websecure"]
      priority: 10
      service: authentik@file
      tls:
        certResolver: cloudflare

    # The signed-in wake page (Beefy-Waker /jf/*). Only /beefy-wake/* is routed
    # here, rewritten to /jf/*, so the waker's LAN admin page, /history and /gate
    # are NOT reachable from the internet.
    jellyfin-wake-page:
      rule: "Host(`jellyfin.holy-grail.ch`) && PathPrefix(`/beefy-wake`)"
      entryPoints: ["websecure"]
      priority: 20
      service: beefy-waker-jf
      middlewares:
        - authentik@file
        - jellyfin-wake-page-rewrite
        - jellyfin-secure-headers
      tls:
        certResolver: cloudflare
```

- [ ] Change the `jellyfin-wake` middleware address to `"http://192.168.1.2:9001/gate?port=8096&policy=jellyfin"` and add under `middlewares`:

```yaml
    jellyfin-wake-page-rewrite:
      replacePathRegex:
        regex: "^/beefy-wake/?(.*)"
        replacement: "/jf/$1"
```

- [ ] Under `services` add:

```yaml
    beefy-waker-jf:
      loadBalancer:
        servers:
          - url: "http://192.168.1.2:9001"
```

- [ ] Update the "ACCEPTED RISK: anonymous requests can wake beefy" comment block: browsers no longer can (sign-in page); non-browser requests still can until the observe-log decision; reference the spec.
- [ ] Traefik reloads dynamic files itself. Verify: `docker logs --since 1m traefik 2>&1 | grep -i error` → nothing about jellyfin.
- [ ] Live checks:
  - `curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://jellyfin.holy-grail.ch/beefy-wake/` → `302 https://sso.holy-grail.ch/...` (or an outpost redirect that ends there).
  - `curl -s -o /dev/null -w '%{http_code}\n' https://jellyfin.holy-grail.ch/System/Info/Public` while beefy is up → `200`.
  - Once beefy is asleep: `curl -s -H 'Accept: text/html' https://jellyfin.holy-grail.ch/ | grep -c 'Sign in to start'` → `1`, and `curl http://192.168.1.2:9001/status` stays `{"up": false}` for 90 s; the waker log shows `observe` with `"decision": "signin"` and no `sent WoL`.
- [ ] Record the Authentik objects in `Docker/Traefik/docs/2026-10-06-authentik-sso.md` (one short section).
- [ ] Commit: `git add Docker/Traefik/traefik/dynamic/jellyfin.yml Docker/Traefik/docs/2026-10-06-authentik-sso.md && git commit -m "Traefik: Jellyfin sign-in-to-wake page behind Authentik, gate policy=jellyfin"`
