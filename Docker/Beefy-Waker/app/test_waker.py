#!/usr/bin/env python3
"""Tests for the Beefy-Waker HTTP server (routing + page-mode contract).

Stdlib only. We spin up the real Handler on an ephemeral port and drive it with
http.client, so we test the actual routing/serving — not mocks. The client-side
state machine (asleep/up/waking) is browser-only and verified by hand.
"""
import http.client
import socket
import http.server
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

# Required env must exist before importing the module (it reads env at import).
os.environ.setdefault("BEEFY_MAC", "00:11:22:33:44:55")
os.environ.setdefault("BEEFY_PROBE_HOST", "127.0.0.1")

import waker  # noqa: E402


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), waker.Handler)
        cls.port = cls.srv.server_address[1]
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, method, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path)
        r = c.getresponse()
        body = r.read().decode()
        c.close()
        return r.status, body

    def test_root_is_manual_mode_with_wake_button(self):
        status, body = self.req("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("AUTOWAKE = false", body)
        self.assertIn('id="wakeBtn"', body)

    def test_wol_is_autowake_mode(self):
        status, body = self.req("GET", "/wol")
        self.assertEqual(status, 200)
        self.assertIn("AUTOWAKE = true", body)

    def test_wake_is_post_only(self):
        status, _ = self.req("GET", "/wake")
        self.assertEqual(status, 405)

    def test_status_returns_up_key(self):
        status, body = self.req("GET", "/status")
        self.assertEqual(status, 200)
        self.assertIn("up", body)

    def test_unknown_path_404(self):
        status, _ = self.req("GET", "/nope")
        self.assertEqual(status, 404)

    def test_page_shows_version_from_file(self):
        vfile = os.path.join(os.path.dirname(os.path.abspath(waker.__file__)), "VERSION")
        with open(vfile) as f:
            expected = "v" + f.read().strip()
        for path in ("/", "/wol"):
            _, body = self.req("GET", path)
            self.assertIn(expected, body)

    def test_handler_has_request_timeout(self):
        # a slow / never-finishing client must not tie up a worker thread forever
        self.assertTrue(waker.Handler.timeout and waker.Handler.timeout > 0)


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
        mock.patch.object(waker, "HOLD_SECONDS", 0.2).start()   # don't hold 25 s per test
        mock.patch.object(waker, "HOLD_POLL_SECONDS", 0.05).start()
        mock.patch.object(waker, "PROBE_TIMEOUT", 0.01).start()   # deadline rule uses it
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(setattr, waker, "_campaign_running", False)

    def gate(self, up, headers, policy="jellyfin"):
        with mock.patch.object(waker, "is_up", return_value=up), \
             mock.patch.object(waker, "is_jellyfin_ready", return_value=up):
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
        self.gate(True, self.BROWSER)                 # /web/ while up: not logged
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

    def test_down_host_booted_but_service_not_yet_up_is_starting(self):
        def probe(host, port):
            return port == waker.PROBE_PORT
        with mock.patch.object(waker, "is_up", side_effect=probe), \
             mock.patch.object(waker, "is_jellyfin_ready", return_value=False):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            c.request("GET", "/gate?port=8096&policy=jellyfin", headers=self.BROWSER)
            r = c.getresponse()
            body = r.read().decode()
            c.close()
        self.assertEqual(r.status, 503)
        self.assertIn("Waking up beefy", body)
        self.send_wol.assert_not_called()

    def test_app_during_campaign_is_starting_no_wake(self):
        waker._campaign_running = True
        status, body = self.gate(False, self.APP)
        self.assertEqual(status, 503)
        self.assertIn("Waking up beefy", body)
        self.send_wol.assert_not_called()

    def test_up_without_policy_passes(self):
        status, _ = self.gate(True, self.BROWSER, policy=None)
        self.assertEqual(status, 200)

    def test_observe_query_keys_bounded(self):
        h = dict(self.APP)
        h["X-Forwarded-Uri"] = "/Items?" + "&".join("k%d=1" % i for i in range(60))
        self.gate(False, h)
        (rec,) = self.observed()
        self.assertEqual(rec["query_keys"], ["<too many>"])

    def test_observe_query_key_truncated(self):
        h = dict(self.APP)
        h["X-Forwarded-Uri"] = "/Items?" + "a" * 100 + "=1"
        self.gate(False, h)
        (rec,) = self.observed()
        self.assertEqual(rec["query_keys"], ["a" * 40])

    def test_observe_double_slash_path_is_matched_and_logged(self):
        self.gate(True, {"X-Forwarded-Uri": "//System/Info/Public"})
        (rec,) = self.observed()
        self.assertEqual(rec["path"], "//System/Info/Public")

    def test_wake_log_uses_probed_port(self):
        self.gate(False, self.APP)
        self.assertIn(":8096)", self.out.getvalue())

    def test_observe_ip_prefers_cf_connecting_ip(self):
        h = dict(self.APP)
        h["CF-Connecting-IP"] = "203.0.113.7"
        h["X-Forwarded-For"] = "6.6.6.6, 203.0.113.7"
        self.gate(False, h)
        (rec,) = self.observed()
        self.assertEqual(rec["ip"], "203.0.113.7")

    def test_observe_emby_authorization_client_and_no_leak(self):
        self.gate(False, {"X-Forwarded-Uri": "/x",
                          "X-Emby-Authorization": 'MediaBrowser Client="Web", Token="EMBYSECRET"',
                          "X-MediaBrowser-Token": "MBSECRET"})
        self.assertNotIn("EMBYSECRET", self.out.getvalue())
        self.assertNotIn("MBSECRET", self.out.getvalue())
        (rec,) = self.observed()
        self.assertEqual(rec["client"], "Web")
        self.assertTrue(rec["x_emby_authorization"])
        self.assertTrue(rec["x_mediabrowser_token"])


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

    def req(self, method, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, headers=headers or {})
        r = c.getresponse()
        body = r.read().decode()
        c.close()
        return r.status, body

    def test_page_gives_up_eventually(self):
        _, body = self.req("GET", "/jf/")
        self.assertIn(str(waker.WAKE_RETRY_WINDOW + 60), body)
        self.assertIn("Try again", body)
        self.assertNotIn("__GIVEUP__", body)

    def test_wake_logs_authentik_user(self):
        status, _ = self.req("POST", "/jf/wake", {"X-Authentik-Username": "alice"})
        self.assertEqual(status, 200)
        self.assertIn("jf wake by alice", sys.stdout.getvalue())

    def test_page_served_at_jf_with_and_without_slash(self):
        for p in ("/jf", "/jf/"):
            status, body = self.req("GET", p)
            self.assertEqual(status, 200, p)
            self.assertIn("/beefy-wake/", body)
            self.assertIn("'wake'", body)
            self.assertIn("'status'", body)
            self.assertIn("/web/", body)
            self.assertNotIn("/history", body)      # no admin panel on the public page

    def test_status_uses_jellyfin_health(self):
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=True) as ready:
            status, body = self.req("GET", "/jf/status")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"up": True})
        ready.assert_called_once_with(waker.PROBE_HOST, waker.JELLYFIN_PORT)

    def test_wake_is_post_only(self):
        status, _ = self.req("GET", "/jf/wake")
        self.assertEqual(status, 405)
        self.send_wol.assert_not_called()
        status, body = self.req("POST", "/jf/wake")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"sent": True})
        self.send_wol.assert_called_once()

    def test_admin_endpoints_not_reachable_under_jf(self):
        for p in ("/jf/history", "/jf/gate", "/jf/wol", "/jf/anything",
                  "/jf/../history", "/jf//history", "/jf/%2e%2e/history"):
            status, _ = self.req("GET", p)
            self.assertEqual(status, 404, p)



class JellyfinReadinessTest(unittest.TestCase):
    """is_jellyfin_ready asks Jellyfin's /health, not just whether the port is open.

    Measured 2026-10-13: Jellyfin's port opens ~5 s before it can serve; in that
    window it answers 200 with a non-API page, then its own 503.
    """

    class Stub(http.server.BaseHTTPRequestHandler):
        status, body, hits = 200, b"Healthy", 0

        def do_GET(self):
            type(self).hits += 1
            self.send_response(type(self).status)
            self.send_header("Content-Length", str(len(type(self).body)))
            self.end_headers()
            self.wfile.write(type(self).body)

        def log_message(self, *a):
            pass

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), cls.Stub)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        waker._ready_until = 0.0
        self.Stub.status, self.Stub.body, self.Stub.hits = 200, b"Healthy", 0
        self.addCleanup(setattr, waker, "_ready_until", 0.0)

    def test_healthy_is_ready(self):
        self.assertTrue(waker.is_jellyfin_ready("127.0.0.1", self.port))

    def test_503_while_starting_is_not_ready(self):
        self.Stub.status, self.Stub.body = 503, b"Jellyfin is starting"
        self.assertFalse(waker.is_jellyfin_ready("127.0.0.1", self.port))

    def test_200_but_not_healthy_is_not_ready(self):
        self.Stub.body = b"<html>startup page</html>"
        self.assertFalse(waker.is_jellyfin_ready("127.0.0.1", self.port))

    def test_nothing_listening_is_not_ready(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); free = s.getsockname()[1]; s.close()
        self.assertFalse(waker.is_jellyfin_ready("127.0.0.1", free))

    def test_positive_result_is_cached_briefly(self):
        self.assertTrue(waker.is_jellyfin_ready("127.0.0.1", self.port))
        self.assertTrue(waker.is_jellyfin_ready("127.0.0.1", self.port))
        self.assertEqual(self.Stub.hits, 1)

    def test_negative_result_is_not_cached(self):
        self.Stub.status = 503
        waker.is_jellyfin_ready("127.0.0.1", self.port)
        waker.is_jellyfin_ready("127.0.0.1", self.port)
        self.assertEqual(self.Stub.hits, 2)

    def test_cache_expires(self):
        waker.is_jellyfin_ready("127.0.0.1", self.port)
        waker._ready_until = 0.0            # as if READY_CACHE_SECONDS passed
        self.Stub.status = 503
        self.assertFalse(waker.is_jellyfin_ready("127.0.0.1", self.port))

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
        mock.patch.object(waker, "PROBE_TIMEOUT", 0.01).start()   # deadline rule uses it
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
        self.assertGreaterEqual(dt, 0.25)   # limit minus the final probe window
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

    def test_clamp_hold_seconds(self):
        self.assertEqual(waker._clamp_hold_seconds("60"), 25.0)
        self.assertEqual(waker._clamp_hold_seconds("-3"), 0.0)
        self.assertEqual(waker._clamp_hold_seconds("12.5"), 12.5)
        self.assertEqual(waker._clamp_hold_seconds("abc"), 18.0)
        self.assertEqual(waker._clamp_hold_seconds(""), 18.0)

    def test_clamp_hold_slots(self):
        self.assertEqual(waker._clamp_hold_slots("0"), 1)
        self.assertEqual(waker._clamp_hold_slots("-4"), 1)
        self.assertEqual(waker._clamp_hold_slots("7"), 7)
        self.assertEqual(waker._clamp_hold_slots("x"), 16)

    def test_subresource_while_starting_is_not_held(self):
        waker._campaign_running = True
        hdr = {"Accept": "*/*", "Sec-Fetch-Dest": "script", "X-Forwarded-Uri": "/web/main.js"}
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=False), \
             mock.patch.object(waker, "HOLD_SECONDS", 5):
            t0 = time.monotonic()
            status, _ = self.gate(hdr)
            dt = time.monotonic() - t0
        self.assertEqual(status, 503)
        self.assertLess(dt, 1)
        self.assertEqual(self.observed()[0]["held"], 0)

    def test_browser_is_not_held_while_starting(self):
        waker._campaign_running = True
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=False), \
             mock.patch.object(waker, "HOLD_SECONDS", 5):
            t0 = time.monotonic()
            status, body = self.gate(self.BROWSER)
            dt = time.monotonic() - t0
        self.assertEqual(status, 503)
        self.assertIn("Waking up beefy", body)
        self.assertLess(dt, 1)
        self.assertEqual(self.observed()[0]["held"], 0)

    def _slots_free(self):
        got = 0
        while waker._hold_slots.acquire(blocking=False):
            got += 1
        for _ in range(got):
            waker._hold_slots.release()
        return got

    def test_slot_released_when_probe_raises(self):
        with mock.patch.object(waker, "is_jellyfin_ready", side_effect=[False, RuntimeError("boom")]), \
             mock.patch.object(waker, "HOLD_SECONDS", 0.2):
            with self.assertRaises(http.client.RemoteDisconnected):   # handler dies in the hold
                self.gate(self.APP)
        self.assertEqual(self._slots_free(), waker.HOLD_SLOTS)

    def test_slot_released_on_normal_path(self):
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=False), \
             mock.patch.object(waker, "HOLD_SECONDS", 0.2):
            self.gate(self.APP)
        self.assertEqual(self._slots_free(), waker.HOLD_SLOTS)

    def test_deadline_counts_time_already_spent(self):
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=False):
            t0 = time.monotonic()
            ready, held = waker.hold_until_ready("h", 1, 0.5, started=t0 - 0.45)
            dt = time.monotonic() - t0
        self.assertFalse(ready)
        self.assertLess(dt, 0.2)


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
        mock.patch.object(waker, "PROBE_TIMEOUT", 0.01).start()   # deadline rule uses it
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

    def test_down_with_cache_is_held_then_served_from_cache(self):
        waker._public_info = self.Stub.body
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=False), \
             mock.patch.object(waker, "HOLD_SECONDS", 0.3):
            t0 = time.monotonic()
            status, body, _ = self.req(self.APP)
            dt = time.monotonic() - t0
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["Id"], "abc123")
        self.assertGreaterEqual(dt, 0.25)   # limit minus the final probe window
        self.send_wol.assert_called_once()
        rec = self.observed()[0]
        self.assertEqual(rec["decision"], "wake"); self.assertTrue(rec["cached"])
        self.assertGreater(rec["held"], 0)

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


    # --- review fixes ---
    @staticmethod
    def _fake_resp(status, data):
        r = mock.MagicMock()
        r.status = status
        r.read.return_value = data
        r.__enter__.return_value = r
        return r

    def _fetch_with(self, resp=None, exc=None):
        with mock.patch("urllib.request.urlopen", side_effect=exc, return_value=resp):
            return waker.fetch_public_info("127.0.0.1", 1)

    def test_fetch_rejects_bad_answers(self):
        fr = self._fake_resp
        self.assertIsNone(self._fetch_with(fr(500, b'{"Id":"x"}')))
        self.assertIsNone(self._fetch_with(fr(200, b"<html>hi</html>")))
        self.assertIsNone(self._fetch_with(fr(200, b"[]")))
        self.assertIsNone(self._fetch_with(fr(200, b"null")))
        self.assertIsNone(self._fetch_with(fr(200, b'{"Version":"1"}')))
        self.assertIsNone(self._fetch_with(fr(200, b'{"Id":"' + b"a" * 70000 + b'"}')))
        self.assertIsNone(waker._public_info)

    def test_fetch_survives_http_exception(self):
        self.assertIsNone(self._fetch_with(exc=http.client.BadStatusLine("x")))

    def test_fetch_takes_timeout(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=self._fake_resp(200, b'{"Id":"a"}')) as m:
            waker.fetch_public_info("h", 1, timeout=1.5)
        self.assertEqual(m.call_args.kwargs["timeout"], 1.5)

    def test_pass_but_relay_fails_serves_cache(self):
        waker._public_info = self.Stub.body
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=True), \
             mock.patch.object(waker, "fetch_public_info", return_value=None):
            status, body, _ = self.req(self.APP)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["Id"], "abc123")

    def test_pass_but_relay_fails_no_cache_is_503(self):
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=True), \
             mock.patch.object(waker, "fetch_public_info", return_value=None):
            status, _, _ = self.req(self.APP)
        self.assertEqual(status, 503)

    def test_200_sends_cors_star(self):
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=True):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            c.request("GET", "/jf/public-info", headers=self.APP)
            r = c.getresponse(); r.read(); c.close()
        self.assertEqual(r.getheader("Access-Control-Allow-Origin"), "*")

    def test_browser_navigation_while_starting_is_not_held(self):
        waker._campaign_running = True
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=False), \
             mock.patch.object(waker, "HOLD_SECONDS", 5):
            t0 = time.monotonic()
            self.req({"Accept": "text/html"})
            dt = time.monotonic() - t0
        self.assertLess(dt, 1)
        self.assertEqual(self.observed()[0]["held"], 0)

    def test_identical_relay_does_not_rewrite_cache(self):
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=True):
            self.req(self.APP)
            with mock.patch("os.replace") as rep:
                self.req(self.APP)
        rep.assert_not_called()
        self.assertFalse(os.path.exists(self.cache.name + ".tmp"))

    def test_observe_has_real_path_method_and_query_keys(self):
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=True):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            c.request("GET", "/jf/public-info?b=1&a=2", headers=self.APP)
            c.getresponse().read(); c.close()
        rec = self.observed()[0]
        self.assertEqual(rec["path"], "/System/Info/Public")
        self.assertEqual(rec["method"], "GET")
        self.assertEqual(rec["query_keys"], ["a", "b"])


    def test_cached_not_served_without_mediabrowser_header(self):
        # jellyfin-web (no Authorization on its connect check) logs the user out when
        # the follow-up authenticated call fails, so it must not be fed the cache.
        waker._public_info = self.Stub.body
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=False), \
             mock.patch.object(waker, "HOLD_SECONDS", 0.3):
            status, body, _ = self.req({"Accept": "application/json"})
        self.assertEqual(status, 503)
        self.assertIn(b"Waking up beefy", body)
        self.assertFalse(self.observed()[0]["cached"])

    def test_cached_served_to_mediabrowser_without_token(self):
        waker._public_info = self.Stub.body
        with mock.patch.object(waker, "is_jellyfin_ready", return_value=False), \
             mock.patch.object(waker, "HOLD_SECONDS", 0.3):
            status, _, _ = self.req({"Accept": "application/json",
                                     "Authorization": 'MediaBrowser Client="X"'})
        self.assertEqual(status, 200)
        self.assertTrue(self.observed()[0]["cached"])

    def test_is_mediabrowser_client(self):
        self.assertTrue(waker.is_mediabrowser_client({"Authorization": ' mediabrowser Client="X"'}))
        self.assertFalse(waker.is_mediabrowser_client({"Authorization": "Bearer x"}))
        self.assertFalse(waker.is_mediabrowser_client({}))


class BrowserSubresourceTest(unittest.TestCase):
    """A browser's own sub-resource requests (favicon, css, js, images) must never wake
    beefy: observed 2026-10-14, the sign-in page's favicon request (Accept image/*,
    Sec-Fetch-Dest image) counted as an app and woke beefy 2 s after the page."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), waker.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def setUp(self):
        waker._campaign_running = False
        self.out = io.StringIO(); mock.patch("sys.stdout", self.out).start()
        self.send_wol = mock.patch.object(waker, "send_wol").start()
        mock.patch.object(waker, "_wake_campaign").start()
        mock.patch.object(waker, "is_up", return_value=False).start()
        mock.patch.object(waker, "is_jellyfin_ready", return_value=False).start()
        mock.patch.object(waker, "HOLD_SECONDS", 5).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(setattr, waker, "_campaign_running", False)

    def gate(self, headers):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/gate?port=8096&policy=jellyfin", headers=headers)
        r = c.getresponse(); body = r.read().decode(); c.close()
        return r.status, body

    def observed(self):
        return [json.loads(l.split("observe ", 1)[1])
                for l in self.out.getvalue().splitlines() if " observe " in l]

    FAVICON = {"Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
               "Sec-Fetch-Dest": "image", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Site": "same-origin",
               "X-Forwarded-Uri": "/favicon.ico", "User-Agent": "Mozilla/5.0 Test"}
    SCRIPT = {"Accept": "*/*", "Sec-Fetch-Dest": "script", "Sec-Fetch-Mode": "no-cors",
              "X-Forwarded-Uri": "/web/main.js"}
    WEB_API = {"Accept": "application/json", "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors",
               "X-Forwarded-Uri": "/System/Info/Public"}
    NATIVE = {"Accept": "*/*", "X-Forwarded-Uri": "/System/Info/Public",
              "Authorization": 'MediaBrowser Client="Android TV", Token="S"'}

    def test_favicon_does_not_wake_or_hold(self):
        t0 = time.monotonic(); status, _ = self.gate(self.FAVICON); dt = time.monotonic() - t0
        self.assertEqual(status, 503); self.assertLess(dt, 1)
        self.send_wol.assert_not_called()
        rec = self.observed()[0]
        self.assertEqual(rec["decision"], "signin"); self.assertEqual(rec["held"], 0)
        self.assertEqual(rec["sec_fetch_dest"], "image")

    def test_script_asset_does_not_wake(self):
        status, _ = self.gate(self.SCRIPT)
        self.assertEqual(status, 503); self.send_wol.assert_not_called()

    def test_browser_fetch_api_call_still_wakes_for_now(self):
        # jellyfin-web's own API fetches (Sec-Fetch-Dest: empty) keep today's behaviour
        # until the observe log says what the TV web apps send.
        with mock.patch.object(waker, "HOLD_SECONDS", 0.2), mock.patch.object(waker, "PROBE_TIMEOUT", 0.01):
            status, _ = self.gate(self.WEB_API)
        self.assertEqual(status, 503); self.send_wol.assert_called_once()

    def test_native_app_still_wakes(self):
        with mock.patch.object(waker, "HOLD_SECONDS", 0.2), mock.patch.object(waker, "PROBE_TIMEOUT", 0.01):
            status, _ = self.gate(self.NATIVE)
        self.assertEqual(status, 503); self.send_wol.assert_called_once()

if __name__ == "__main__":
    unittest.main()
