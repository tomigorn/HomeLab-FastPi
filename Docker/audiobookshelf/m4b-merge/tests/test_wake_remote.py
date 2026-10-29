#!/usr/bin/env python3
"""wake_remote() asks the Beefy-Waker with the X-Wake header it requires (CSRF guard).

Run: ./tests/test_wake_remote.py
"""
import importlib.util
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("orch", os.path.join(HERE, "orchestrate.py"))
orch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orch)


class WakeRemote(unittest.TestCase):
    def test_posts_with_the_waker_header(self):
        seen = {}

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                seen.update(method=self.command, wake=self.headers.get("X-Wake"))
                body = b'{"sent": true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.addCleanup(srv.server_close)
        threading.Thread(target=srv.handle_request, daemon=True).start()
        orch.WAKER_URL = f"http://127.0.0.1:{srv.server_address[1]}/wake"
        orch.ssh = lambda script, timeout=None: SimpleNamespace(returncode=0)
        self.assertTrue(orch.wake_remote(timeout=5))
        self.assertEqual(seen, {"method": "POST", "wake": "1"})


if __name__ == "__main__":
    unittest.main()
