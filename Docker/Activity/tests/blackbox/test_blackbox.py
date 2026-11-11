#!/usr/bin/env python3
"""Black-box tests for the activity service: real HTTP against the running binary, fakes on loopback.

Runs inside a network-less container (run.sh):
  127.0.0.1:18080  the service (SUT)
  127.0.0.2:8097   activity-gate on beefy (serves /fixtures, records every request)
  127.0.0.3:9001   Beefy-Waker /status
  127.0.0.4:8080   Audiobookshelf
  127.0.0.5:8080   qBittorrent (mouse)
"""
import http.client
import json
import os
import pathlib
import shutil
import socket
import subprocess
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SUT = os.environ.get("SUT", "/sut/activity")
FIX = pathlib.Path("/fixtures")
TMP = pathlib.Path("/tmp/bb")
PORT = 18080
CONTRACT = {
    "/jellyfin/Sessions?ActiveWithinSeconds=60": "sessions.json",
    "/radarr/api/v3/queue?pageSize=200&includeMovie=true": "radarr-queue.json",
    "/sonarr/api/v3/queue?pageSize=500&includeSeries=true&includeEpisode=true": "sonarr-queue.json",
    "/sonarr/api/v3/series": "sonarr-series.json",
    "/seerr/request-state.json": "request-state.json",
    "/seerr/night-waiting.json": "night-waiting.json",
}
# Every invented title, user, device, path and id in the fixtures: none may leave the service.
LEAKS = ["fixture", "jane", "john", "max muster", "erika", "idle person", "pilot", "fakesid", "night1", "abc123",
         "nzo_", "/data/", "movie/", "tv/", "displaytitle", "username", "fixture-key", "fixture-pass"]


def wait_for(cond, timeout, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


class Fake:
    """Threaded HTTP fake; `handler(method, path, headers, body)` -> (status, headers, body) or None to drop the connection."""

    def __init__(self, host, port, handler):
        self.handler = handler
        self.requests = []
        self.lock = threading.Lock()
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _do(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                hdrs = {k.lower(): v for k, v in self.headers.items()}
                with fake.lock:
                    fake.requests.append((self.command, self.path, hdrs))
                out = fake.handler(self.command, self.path, hdrs, body)
                if out is None:
                    self.close_connection = True
                    return
                status, headers, data = out
                self.send_response(status)
                for k, v in headers:
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(data)
                except ConnectionError:
                    pass
                self.close_connection = True

            do_GET = do_POST = do_PUT = _do

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer((host, port), H)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def reset(self):
        with self.lock:
            self.requests = []

    def seen(self):
        with self.lock:
            return list(self.requests)


class World:
    def __init__(self):
        self.waker_up = "up"
        self.gate_mode = "ok"
        self.abs_mode = "ok"
        self.waker = Fake("127.0.0.3", 9001, self.on_waker)
        self.gate = Fake("127.0.0.2", 8097, self.on_gate)
        self.abs = Fake("127.0.0.4", 8080, self.on_abs)
        self.qbit = Fake("127.0.0.5", 8080, self.on_qbit)

    def on_waker(self, method, path, h, body):
        if path != "/status":
            return 404, [], b"no"
        if self.waker_up == "broken":
            return 502, [], b"<html>bad gateway</html>"
        up = "true" if self.waker_up == "up" else "false"
        return 200, [("Content-Type", "application/json")], f'{{"up": {up}, "phase": "idle", "seconds_left": null, "reason": ""}}'.encode()

    def on_gate(self, method, path, h, body):
        if self.gate_mode == "down":
            return 503, [], b"gate down"
        if self.gate_mode == "huge" and path.startswith("/radarr/"):
            return 200, [("Content-Type", "application/json")], b'{"records": [' + b'{"movieId": 1, "title": "Fixture filler"},' * 120000 + b"{}]}"
        name = CONTRACT.get(path)
        if method != "GET" or name is None:
            return 403, [], b"not allowed"
        return 200, [("Content-Type", "application/json")], (FIX / name).read_bytes()

    def on_abs(self, method, path, h, body):
        if self.abs_mode != "ok" or h.get("authorization") != "Bearer fixture-key":
            return 401, [], b"Unauthorized"
        if path != "/api/sessions/open":
            return 404, [], b"no"
        data = json.loads((FIX / "abs-sessions.json").read_text())
        now = int(time.time() * 1000)
        for s in data["sessions"] + data["shareSessions"]:
            s["updatedAt"] += now
        return 200, [("Content-Type", "application/json")], json.dumps(data).encode()

    def on_qbit(self, method, path, h, body):
        if method == "POST" and path == "/api/v2/auth/login" and b"password=fixture-pass" in body:
            return 200, [("Set-Cookie", "SID=fakesid; HttpOnly; path=/")], b"Ok."
        if path == "/api/v2/torrents/info?category=abr" and h.get("cookie") == "SID=fakesid":
            return 200, [("Content-Type", "application/json")], (FIX / "qbit-abr.json").read_bytes()
        return 403, [], b"Forbidden"


W = None


def setUpModule():
    global W
    W = World()


class Sut:
    def __init__(self, env):
        TMP.mkdir(parents=True, exist_ok=True)
        (TMP / "key").write_text("fixture-key\n")
        (TMP / "pass").write_text("fixture-pass\n")
        (TMP / "data").mkdir(exist_ok=True)
        self.env = {
            "LISTEN_ADDR": "127.0.0.1", "LISTEN_PORT": str(PORT),
            "WAKER_URL": "http://127.0.0.3:9001", "GATE_URL": "http://127.0.0.2:8097",
            "ABS_URL": "http://127.0.0.4:8080", "ABS_KEY_FILE": str(TMP / "key"),
            "QBIT_URL": "http://127.0.0.5:8080", "QBIT_PASS_FILE": str(TMP / "pass"),
            "DATA_DIR": str(TMP / "data"), "POLL_SECONDS": "1", "WAKER_SECONDS": "1",
            "PAGE_ALLOW": "127.0.0.1/32", "METRICS_ALLOW": "127.0.0.1/32", "PATH": "/usr/bin:/bin",
        }
        self.env.update(env)
        self.lines = []
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen([SUT], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        threading.Thread(target=self._read, daemon=True).start()
        if not wait_for(self._listening, 10):
            self.stop()
            raise RuntimeError("SUT did not start:\n" + self.log())

    def _listening(self):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
            return True
        except OSError:
            return False

    def _read(self):
        try:
            for line in self.proc.stdout:  # closed by stop()
                self.lines.append(line.rstrip("\n"))
        except ValueError:
            pass

    def log(self):
        return "\n".join(self.lines)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.proc:
            self.proc.stdout.close()
        wait_for(lambda: not self._listening(), 3)


def get(path, source="127.0.0.1"):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10, source_address=(source, 0))
    c.request("GET", path)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, data


def state():
    s, _, body = get("/api/state")
    assert s == 200, s
    return json.loads(body)


class Base(unittest.TestCase):
    env = {}
    waker = "up"

    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        W.waker_up, W.gate_mode, W.abs_mode = self.waker, "ok", "ok"
        for f in (W.waker, W.gate, W.abs, W.qbit):
            f.reset()
        self.sut = Sut(self.env)
        self.sut.start()
        self.addCleanup(lambda: self.sut.stop())

    def wait_state(self, cond, timeout=8):
        box = {}

        def ok():
            box["s"] = state()
            return cond(box["s"])

        self.assertTrue(wait_for(ok, timeout), f"state never matched: {box.get('s')}\nlog:\n{self.sut.log()}")
        return box["s"]


EXPECTED_WATCHING = [
    {"kind": "Movie", "quality": "4K HDR", "mode": "direct play", "paused": False, "n": 2},
    {"kind": "Movie", "quality": "1080p HDR", "mode": "direct stream", "paused": False, "n": 1},
    {"kind": "Episode", "quality": "1080p SDR", "mode": "transcode", "paused": False, "n": 1},
    {"kind": "Episode", "quality": "1080p SDR", "mode": "transcode", "paused": True, "n": 1},
    {"kind": "Anime", "quality": "1080p SDR", "mode": "transcode (audio)", "paused": False, "n": 1},
    {"kind": "Other", "quality": None, "mode": "direct play", "paused": False, "n": 1},
]


class Awake(Base):
    def test_live_counts_from_the_gate(self):
        s = self.wait_state(lambda s: s["beefy_data"] == "live" and s["listening"] is not None and s["audiobook_downloads"] is not None)
        self.assertEqual(s["beefy"], "up")
        self.assertEqual(s["watching"], EXPECTED_WATCHING)
        self.assertEqual(len(s["downloads"]), 11)
        self.assertIn({"state": "waiting for night", "kind": "Episode", "quality": None, "items": 1, "seasons": 2, "episodes": 18}, s["downloads"])
        self.assertIn({"state": "downloading", "kind": "Anime", "quality": "1080p SDR", "items": 1, "seasons": 2, "episodes": 4}, s["downloads"])
        self.assertIsNone(s["downloads_as_of"])
        self.assertEqual(s["listening"], {"sessions": 3})
        self.assertEqual(s["audiobook_downloads"], {"downloading": 3, "queued": 1})

    def test_gate_requests_are_contract_gets_with_connection_close(self):
        self.wait_state(lambda s: s["beefy_data"] == "live")
        seen = W.gate.seen()
        self.assertTrue(seen)
        for method, path, h in seen:
            self.assertEqual(method, "GET")
            self.assertIn(path, CONTRACT)
            self.assertEqual(h.get("connection", "").lower(), "close", path)
            self.assertNotIn("x-api-key", h)
            self.assertNotIn("authorization", h)

    def test_one_attempt_per_path_per_tick(self):
        self.wait_state(lambda s: s["beefy_data"] == "live")
        W.gate_mode = "down"
        W.gate.reset()
        time.sleep(3.5)
        n = len(W.gate.seen())
        self.assertLessEqual(n, 4, "a failing gate gets at most one request per tick (first required path fails)")
        self.assertGreaterEqual(n, 2)

    def test_gate_down_while_awake_shows_unavailable_not_old_streams(self):
        W.gate_mode = "down"
        s = self.wait_state(lambda s: s["beefy"] == "up")
        time.sleep(2)
        s = state()
        self.assertIsNone(s["watching"])
        self.assertEqual(s["beefy_data"], "none")
        self.assertIn("beefy poll failed: /jellyfin/Sessions?ActiveWithinSeconds=60: HTTP 503", self.sut.log())
        self.assertEqual(self.sut.log().count("beefy poll failed"), 1, "logged once per change, not every tick")

    def test_oversized_answer_fails_the_poll_without_crash(self):
        W.gate_mode = "huge"
        time.sleep(3)
        self.assertIsNone(self.sut.proc.poll())
        self.assertIn("answer over", self.sut.log())
        self.assertEqual(state()["beefy_data"], "none")

    def test_nothing_identifying_leaves_the_service(self):
        self.wait_state(lambda s: s["beefy_data"] == "live" and s["listening"] is not None)
        _, _, metrics = get("/metrics")
        _, _, page = get("/")
        out = [json.dumps(state()), metrics.decode(), self.sut.log(), (TMP / "data" / "last.json").read_text()]
        blob = "\n".join(out).lower()
        for leak in LEAKS:
            self.assertNotIn(leak, blob)
        self.assertIn('activity_streams{kind="Movie",quality="4K HDR",mode="direct play"} 2', metrics.decode())
        self.assertIn(b"<html", page)

    def test_access_rules_and_headers(self):
        s, h, _ = get("/")
        self.assertEqual(s, 200)
        self.assertIn("frame-ancestors 'none'", h["content-security-policy"])
        self.assertEqual(h["cache-control"], "no-store")
        self.assertEqual(get("/api/state", source="127.0.0.9")[0], 403)
        self.assertEqual(get("/", source="127.0.0.9")[0], 403)
        self.assertEqual(get("/metrics", source="127.0.0.9")[0], 403)
        self.assertEqual(get("/health", source="127.0.0.9")[0], 200)
        self.assertEqual(get("/ingest")[0], 404)

    def test_health_subcommand(self):
        r = subprocess.run([SUT, "--health"], env={"LISTEN_PORT": str(PORT)}, timeout=10)
        self.assertEqual(r.returncode, 0)


class PageViews(Base):
    env = {"POLL_SECONDS": "3600", "WAKER_SECONDS": "3600"}

    def test_page_views_never_reach_beefy(self):
        self.wait_state(lambda s: s["beefy_data"] == "live")
        before = len(W.gate.seen())
        for _ in range(20):
            get("/")
            get("/api/state")
            get("/metrics")
        time.sleep(1)
        self.assertEqual(len(W.gate.seen()), before)


class Asleep(Base):
    waker = "down"

    def test_asleep_means_no_request_to_beefy(self):
        s = self.wait_state(lambda s: s["beefy"] == "asleep")
        time.sleep(3)
        self.assertEqual(W.gate.seen(), [])
        self.assertGreaterEqual(len(W.waker.seen()), 2)
        s = state()
        self.assertEqual(s["watching"], [])
        self.assertIsNone(s["downloads"])

    def test_falling_asleep_keeps_downloads_as_of(self):
        W.waker_up = "up"
        live = self.wait_state(lambda s: s["beefy_data"] == "live")
        W.waker_up = "down"
        W.gate.reset()
        s = self.wait_state(lambda s: s["beefy"] == "asleep")
        self.assertEqual(s["watching"], [])
        self.assertEqual(s["downloads"], live["downloads"])
        self.assertIsInstance(s["downloads_as_of"], int)
        self.assertLessEqual(abs(s["downloads_as_of"] - int(time.time())), 5)
        time.sleep(2)
        self.assertEqual(W.gate.seen(), [])

    def test_restart_keeps_the_last_downloads(self):
        W.waker_up = "up"
        live = self.wait_state(lambda s: s["beefy_data"] == "live")
        W.waker_up = "down"
        self.sut.stop()
        self.sut = Sut(self.env)
        self.sut.start()
        s = self.wait_state(lambda s: s["beefy"] == "asleep")
        self.assertEqual(s["downloads"], live["downloads"])
        self.assertIsNotNone(s["downloads_as_of"])
        self.assertEqual(s["beefy_data"], "stale")
        self.assertIn("loaded the last snapshot", self.sut.log())


class WakerBroken(Base):
    waker = "broken"

    def test_unknown_waker_never_polls_beefy(self):
        s = self.wait_state(lambda s: s["listening"] is not None)
        time.sleep(2)
        self.assertEqual(state()["beefy"], "unknown")
        self.assertIsNone(state()["watching"])
        self.assertEqual(W.gate.seen(), [])


class LocalSources(Base):
    waker = "down"

    def test_abs_unavailable_rest_still_works(self):
        W.abs_mode = "deny"
        s = self.wait_state(lambda s: s["audiobook_downloads"] is not None)
        self.assertIsNone(s["listening"])
        self.assertEqual(s["audiobook_downloads"], {"downloading": 3, "queued": 1})
        self.assertEqual(s["beefy"], "asleep")
        self.assertIn("local source unavailable: audiobookshelf: HTTP 401", self.sut.log())



class MissingCredential(Base):
    waker = "down"
    env = {"QBIT_PASS_FILE": "/tmp/bb/missing"}

    def test_missing_qbit_credential_is_unavailable(self):
        s = self.wait_state(lambda s: s["listening"] is not None)
        self.assertIsNone(s["audiobook_downloads"])
        self.assertEqual(s["listening"], {"sessions": 3})
        self.assertIn("qbittorrent: secret file unreadable", self.sut.log())


if __name__ == "__main__":
    unittest.main()
