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


if __name__ == "__main__":
    unittest.main()
