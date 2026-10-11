#!/usr/bin/env python3
"""Tests for the Beefy-Waker HTTP server (routing + page-mode contract).

Stdlib only. We spin up the real Handler on an ephemeral port and drive it with
http.client, so we test the actual routing/serving — not mocks. The client-side
state machine (asleep/up/waking) is browser-only and verified by hand.
"""
import http.client
import os
import threading
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


if __name__ == "__main__":
    unittest.main()
