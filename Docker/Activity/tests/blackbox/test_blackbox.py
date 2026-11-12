#!/usr/bin/env python3
"""Black-box tests for the activity service: real HTTP against the running binary, fakes on loopback.

Runs inside a network-less container (run.sh):
  127.0.0.1:18080                the service (SUT)
  127.0.0.2:8095/activity/gate   activity-gate on beefy behind Traefik's internal route (serves /fixtures, records every request)
  127.0.0.3:9001/activity/waker  Beefy-Waker /status behind Traefik's internal route
  127.0.0.4:8080                 Audiobookshelf
  127.0.0.5:8080/activity/qbit   qBittorrent (mouse) behind Traefik's internal route: no login (Traefik is whitelisted), only GET torrents/info?category=abr
The fakes play the Traefik routes: a request outside the prefix is 404, the recorded path is the one after the prefix.
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
         "nzo_", "/data/", "movie/", "tv/", "displaytitle", "username", "fixture-key", "fixture-pass",
         "u-jane", "u-john", "u-max", "u-erika", "u-idle", "userid", "203.0.113", "192.168.1.5", "192.168.1.6", "10.8.0.3", "fe80", "::ffff",
         "remoteendpoint", "jellyfin web", "android tv", "devicename", "abc1", "ani1", "stl1"]


def wait_for(cond, timeout, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


class Fake:
    """Threaded HTTP fake; `handler(method, path, headers, body)` -> (status, headers, body) or None to drop the connection."""

    def __init__(self, host, port, handler, prefix=""):
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
                path = self.path[len(prefix):] if self.path.startswith(prefix + "/") else None
                with fake.lock:
                    fake.requests.append((self.command, path if path is not None else self.path, hdrs))
                out = fake.handler(self.command, path, hdrs, body) if path is not None else (404, [], b"404 page not found")
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
        self.waker_phase = "idle"
        self.gate_mode = "ok"
        self.gate_delay = 0.0
        self.abs_mode = "ok"
        self.qbit_mode = "ok"
        self.waker = Fake("127.0.0.3", 9001, self.on_waker, "/activity/waker")
        self.gate = Fake("127.0.0.2", 8095, self.on_gate, "/activity/gate")
        self.abs = Fake("127.0.0.4", 8080, self.on_abs)
        self.qbit = Fake("127.0.0.5", 8080, self.on_qbit, "/activity/qbit")

    def on_waker(self, method, path, h, body):
        if path != "/status":
            return 404, [], b"no"
        if self.waker_up == "broken":
            return 502, [], b"<html>bad gateway</html>"
        up = "true" if self.waker_up == "up" else "false"
        return 200, [("Content-Type", "application/json")], f'{{"up": {up}, "phase": "{self.waker_phase}", "seconds_left": null, "reason": ""}}'.encode()

    def on_gate(self, method, path, h, body):
        if self.gate_delay:
            time.sleep(self.gate_delay)
        if self.gate_mode == "down":
            return 503, [], b"gate down"
        if self.gate_mode == "sonarr-down" and path.startswith("/sonarr/api/v3/queue"):
            return 503, [], b"sonarr restarting"
        if self.gate_mode == "gaps" and path in ("/sonarr/api/v3/series", "/seerr/night-waiting.json"):
            return 503, [], b"busy"
        if self.gate_mode == "gaps" and path.startswith("/radarr/"):
            q = json.loads((FIX / "radarr-queue.json").read_text())
            q["totalRecords"] = 999
            return 200, [("Content-Type", "application/json")], json.dumps(q).encode()
        if self.gate_mode == "huge" and path.startswith("/radarr/"):
            return 200, [("Content-Type", "application/json")], b'{"records": [' + b'{"movieId": 1, "title": "Fixture filler"},' * 120000 + b"{}]}"
        if self.gate_mode == "new-series" and path.startswith("/sonarr/api/v3/queue"):
            q = json.loads((FIX / "sonarr-queue.json").read_text())
            q["records"].append({"id": 99, "seriesId": 299, "status": "downloading", "trackedDownloadState": "downloading", "series": {"seriesType": "standard"}})
            return 200, [("Content-Type", "application/json")], json.dumps(q).encode()
        name = CONTRACT.get(path)
        if method != "GET" or name is None:
            return 403, [], b"not allowed"
        data = (FIX / name).read_bytes()
        if path.startswith("/seerr/"):
            # like nginx serving a static file: ETag, and 304 for a matching If-None-Match
            etag = '"%x-%x"' % (len(data), hash(data) & 0xFFFFFF)
            if h.get("if-none-match") == etag:
                return 304, [("ETag", etag)], b""
            return 200, [("Content-Type", "application/json"), ("ETag", etag)], data
        return 200, [("Content-Type", "application/json")], data

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
        if self.qbit_mode == "ok" and method == "GET" and path == "/api/v2/torrents/info?category=abr":
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
        (TMP / "data").mkdir(exist_ok=True)
        self.env = {
            "LISTEN_ADDR": "127.0.0.1", "LISTEN_PORT": str(PORT),
            "WAKER_URL": "http://127.0.0.3:9001/activity/waker", "GATE_URL": "http://127.0.0.2:8095/activity/gate",
            "ABS_URL": "http://127.0.0.4:8080", "ABS_KEY_FILE": str(TMP / "key"),
            "QBIT_URL": "http://127.0.0.5:8080/activity/qbit",
            "DATA_DIR": str(TMP / "data"), "POLL_SECONDS": "1", "VIEWER_SECONDS": "10",
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
        W.waker_up, W.waker_phase, W.gate_mode, W.gate_delay, W.abs_mode, W.qbit_mode = self.waker, "idle", "ok", 0.0, "ok", "ok"
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


ABR = {"downloading": 5, "queued": 1, "paused": 2, "problem": 2, "eta": 600, "left": 170000000}
NO_TC = {"accel": None, "reasons": []}
EXPECTED_WATCHING = [
    {"kind": "Movie", "quality": "4K HDR", "mode": "direct play", "paused": False, "n": 2, **NO_TC},
    {"kind": "Movie", "quality": "1080p HDR", "mode": "direct stream", "paused": False, "n": 1, **NO_TC},
    {"kind": "Episode", "quality": "1080p SDR", "mode": "transcode", "paused": False, "n": 1, "accel": "QSV", "reasons": ["HDR tone-mapping", "bitrate limit"]},
    {"kind": "Episode", "quality": "1080p SDR", "mode": "transcode", "paused": True, "n": 1, "accel": "QSV", "reasons": ["subtitles"]},
    {"kind": "Anime", "quality": "1080p SDR", "mode": "transcode (audio)", "paused": False, "n": 1, "accel": None, "reasons": ["audio"]},
    {"kind": "Music", "quality": None, "mode": "direct play", "paused": False, "n": 1, **NO_TC},
]


class Awake(Base):
    def test_live_counts_from_the_gate(self):
        s = self.wait_state(lambda s: s["beefy_data"] == "live" and s["listening"] is not None and s["audiobook_downloads"] is not None)
        self.assertEqual(s["beefy"], "up")
        self.assertEqual(s["watching"], EXPECTED_WATCHING)
        self.assertEqual(len(s["downloads"]), 15)
        self.assertEqual(s["downloads_gaps"], {"series_unavailable": False, "night_unavailable": False, "truncated": False})
        self.assertIn({"state": "waiting for night", "kind": "Episode", "quality": None, "items": 1, "seasons": 2, "episodes": 18, "eta": None, "left": None}, s["downloads"])
        self.assertIn({"state": "downloading", "kind": "Anime", "quality": "1080p SDR", "items": 1, "seasons": 2, "episodes": 4, "eta": 93784, "left": 4000000000}, s["downloads"])
        self.assertEqual(s["watching_summary"], {"bitrate_kbps": 142960, "lan": 4, "remote": 3, "people": 4})
        self.assertIsNone(s["downloads_as_of"])
        self.assertIs(s["night_open"], False, "night-waiting.json low_tariff")
        self.assertEqual(s["listening"], {"sessions": 3})
        self.assertEqual(s["audiobook_downloads"], ABR)

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
        W.waker.reset()
        time.sleep(3.5)
        polls, n = len(W.waker.seen()), len(W.gate.seen())
        self.assertGreaterEqual(polls, 2)
        self.assertLessEqual(n, 5 * polls, "a failing gate gets one request per needed path per tick, no retries")
        self.assertGreaterEqual(n, 2)

    def test_gate_down_while_awake_shows_unavailable_not_old_streams(self):
        W.gate_mode = "down"
        s = self.wait_state(lambda s: s["beefy"] == "up")
        time.sleep(2)
        s = state()
        self.assertIsNone(s["watching"])
        self.assertEqual(s["beefy_data"], "none")
        self.assertTrue(s["streams_failed"] and s["downloads_failed"], "the page warns: beefy data unavailable (gate not answering)")
        self.assertIn("/jellyfin/Sessions?ActiveWithinSeconds=60: HTTP 503", self.sut.log())
        self.assertEqual(self.sut.log().count("beefy poll failed"), 1, "logged once per change, not every tick")

    def test_a_queue_failure_keeps_the_streams(self):
        W.gate_mode = "sonarr-down"
        s = self.wait_state(lambda s: s["beefy_data"] == "live")
        self.assertEqual(s["watching"], EXPECTED_WATCHING)
        self.assertIsNone(s["downloads"], "no queue answer yet")
        self.assertTrue(s["downloads_failed"])
        self.assertFalse(s["streams_failed"])
        W.gate_mode = "ok"
        live = self.wait_state(lambda s: s["downloads"] is not None and s["downloads_as_of"] is None)
        W.gate_mode = "sonarr-down"
        s = self.wait_state(lambda s: s["downloads_failed"])
        self.assertEqual(s["watching"], EXPECTED_WATCHING)
        self.assertEqual(s["downloads"], live["downloads"], "the last downloads stay")
        time.sleep(1.5)
        self.assertEqual(state()["downloads"], live["downloads"])
        self.assertIn("/sonarr/api/v3/queue?pageSize=500&includeSeries=true&includeEpisode=true: HTTP 503", self.sut.log())

    def test_series_list_is_cached_and_request_state_conditional(self):
        self.wait_state(lambda s: s["beefy_data"] == "live")
        time.sleep(3.5)
        paths = [p for _, p, _ in W.gate.seen()]
        polls = paths.count("/jellyfin/Sessions?ActiveWithinSeconds=60")
        self.assertGreaterEqual(polls, 3)
        self.assertEqual(paths.count("/sonarr/api/v3/series"), 1, "the series list is read once, then reused")
        conds = [h.get("if-none-match") for _, p, h in W.gate.seen() if p == "/seerr/request-state.json"]
        self.assertIsNone(conds[0])
        self.assertTrue(all(conds[1:]), "later reads of request-state.json are conditional")
        self.assertEqual(len(state()["downloads"]), 15, "a 304 keeps the last request state")
        self.assertLessEqual(abs(len(W.waker.seen()) - polls), 1, "the Waker is asked once per poll")
        W.gate_mode = "new-series"
        time.sleep(3)
        paths = [p for _, p, _ in W.gate.seen()]
        self.assertEqual(paths.count("/sonarr/api/v3/series"), 2, "an unknown series id refreshes the list once, not every poll")

    def test_gaps_are_flagged_and_logged(self):
        W.gate_mode = "gaps"
        s = self.wait_state(lambda s: s["downloads"] is not None)
        self.assertEqual(s["downloads_gaps"], {"series_unavailable": True, "night_unavailable": True, "truncated": True})
        self.assertTrue(s["streams_series_unavailable"])
        self.assertEqual(s["beefy_data"], "live", "a missing series list does not fail the streams")
        kinds = {w["kind"] for w in s["watching"]}
        self.assertNotIn("Anime", kinds, "without the series list anime counts as Episode")
        log = self.sut.log()
        self.assertIn("beefy poll incomplete: /sonarr/api/v3/series: HTTP 503", log)
        self.assertIn("/seerr/night-waiting.json: HTTP 503", log)
        self.assertIn("radarr queue truncated: 9 of 999 records", log)
        self.assertEqual(log.count("beefy poll incomplete"), 1, "once per change")

    def test_oversized_answer_fails_the_poll_without_crash(self):
        W.gate_mode = "huge"
        state()
        time.sleep(3)
        self.assertIsNone(self.sut.proc.poll())
        self.assertIn("answer over", self.sut.log())
        s = state()
        self.assertEqual(s["beefy_data"], "live", "only the downloads part fails")
        self.assertIsNone(s["downloads"])
        self.assertTrue(s["downloads_failed"])

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
        s, h, page = get("/")
        self.assertEqual(s, 200)
        csp = h["content-security-policy"]
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn("unsafe-inline", csp)
        import base64, hashlib, re
        for tag, directive in (("script", "script-src"), ("style", "style-src")):
            blocks = re.findall(rf"<{tag}>(.*?)</{tag}>".encode(), page, re.S)
            self.assertEqual(len(blocks), 1, tag)
            digest = base64.b64encode(hashlib.sha256(blocks[0]).digest()).decode()
            self.assertIn(f"{directive} 'sha256-{digest}'", csp)
        self.assertEqual(h["cache-control"], "no-store")
        for path in ("/api/state", "/", "/metrics", "/health"):
            with self.assertRaises(OSError, msg=f"{path}: a peer in neither allow-list is dropped at accept"):
                get(path, source="127.0.0.9")
        self.assertEqual(get("/ingest")[0], 404)

    def test_unlisted_peers_cannot_starve_the_listed_ones(self):
        held = []
        for _ in range(80):
            try:
                held.append(socket.create_connection(("127.0.0.1", PORT), timeout=1, source_address=("127.0.0.9", 0)))
            except OSError:
                pass
        try:
            self.assertEqual(get("/health")[0], 200, "silent connections of a neighbour take no slot")
        finally:
            for c in held:
                c.close()

    def test_health_subcommand(self):
        r = subprocess.run([SUT, "--health"], env={"LISTEN_PORT": str(PORT)}, timeout=10)
        self.assertEqual(r.returncode, 0)


def requests_made():
    return {"waker": len(W.waker.seen()), "gate": len(W.gate.seen()), "abs": len(W.abs.seen()), "qbit": len(W.qbit.seen())}


NOTHING = {"waker": 0, "gate": 0, "abs": 0, "qbit": 0}


class PageViews(Base):
    env = {"POLL_SECONDS": "3600"}

    def test_idle_service_asks_nobody(self):
        time.sleep(4)
        self.assertEqual(requests_made(), NOTHING)

    def test_metrics_health_and_html_are_no_viewers(self):
        for _ in range(10):
            get("/metrics")
            get("/health")
            get("/")
        time.sleep(2)
        self.assertEqual(requests_made(), NOTHING)
        _, _, m = get("/metrics")
        self.assertIn("activity_viewer_active 0\n", m.decode())
        self.assertNotIn("activity_last_poll_timestamp_seconds", m.decode())

    def test_first_view_polls_once_at_once(self):
        s = state()
        self.assertEqual(s["beefy_data"], "live", "the first answer already carries the immediate poll")
        self.assertEqual(s["listening"], {"sessions": 3})
        self.assertIsInstance(s["polled_at"], int)
        made = requests_made()
        self.assertEqual((made["waker"], made["abs"], made["qbit"]), (1, 1, 1))
        paths = [p for _, p, _ in W.gate.seen()]
        self.assertEqual(sorted(paths), sorted(set(paths)), "one request per gate path")
        for _ in range(20):
            get("/")
            get("/api/state")
            get("/metrics")
        time.sleep(1)
        self.assertEqual(requests_made(), made, "views within the window add no poll")
        _, _, m = get("/metrics")
        self.assertIn("activity_viewer_active 1\n", m.decode())
        self.assertIn("activity_last_poll_timestamp_seconds ", m.decode())

    def test_a_slow_gate_still_answers_the_first_view_live(self):
        W.gate_delay = 1.0
        t0 = time.monotonic()
        s = state()
        self.assertEqual(s["beefy_data"], "live", f"the gate requests run side by side (1 s each), so the 4 s first-view wait is enough; took {time.monotonic() - t0:.1f} s")

    def test_concurrent_first_views_share_one_poll(self):
        out = []
        ts = [threading.Thread(target=lambda: out.append(state())) for _ in range(6)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(out), 6)
        self.assertTrue(all(s["beefy_data"] == "live" for s in out), out)
        self.assertEqual(requests_made()["waker"], 1)


class ViewerWindow(Base):
    env = {"VIEWER_SECONDS": "2"}

    def test_polling_stops_after_the_window(self):
        state()
        time.sleep(1.5)
        self.assertGreaterEqual(requests_made()["waker"], 2, "polls every POLL_SECONDS while viewed")
        time.sleep(1.5)
        for f in (W.waker, W.gate, W.abs, W.qbit):
            f.reset()
        time.sleep(3)
        self.assertEqual(requests_made(), NOTHING)


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
        self.assertIn("loaded the last downloads", self.sut.log())


class WakerPhases(Base):
    waker = "down"

    def test_waking_and_broken_are_shown_as_such(self):
        W.waker_phase = "waking"
        s = self.wait_state(lambda s: s["beefy"] == "waking")
        self.assertEqual(s["watching"], [])
        W.waker_phase = "broken"
        s = self.wait_state(lambda s: s["beefy"] == "broken")
        self.assertIsNone(s["watching"])
        self.assertEqual(W.gate.seen(), [], "never asks beefy unless it is up")


class Config(unittest.TestCase):
    def test_nonsense_timing_is_refused(self):
        for env in ({"POLL_SECONDS": "0"}, {"VIEWER_SECONDS": "0"}, {"POLL_SECONDS": "soon"}):
            r = subprocess.run([SUT], env={"LISTEN_ADDR": "127.0.0.1", "LISTEN_PORT": "18081", "DATA_DIR": "off", **env}, capture_output=True, text=True, timeout=10)
            self.assertEqual(r.returncode, 2, env)
            self.assertIn(next(iter(env)), r.stderr)


class WakerBroken(Base):
    waker = "broken"

    def test_unknown_waker_never_polls_beefy(self):
        s = self.wait_state(lambda s: s["listening"] is not None)
        time.sleep(2)
        self.assertEqual(state()["beefy"], "unknown")
        self.assertIsNone(state()["watching"])
        self.assertEqual(W.gate.seen(), [])


    def test_waker_turning_unknown_hides_fresh_streams(self):
        W.waker_up = "up"
        live = self.wait_state(lambda s: s["beefy_data"] == "live")
        W.waker_up = "broken"
        s = self.wait_state(lambda s: s["beefy"] == "unknown")
        self.assertIsNone(s["watching"], "unknown = unavailable, even with a snapshot seconds old")
        self.assertEqual(s["beefy_data"], "stale")
        self.assertEqual(s["downloads"], live["downloads"])
        self.assertIsInstance(s["downloads_as_of"], int)


class LocalSources(Base):
    waker = "down"

    def test_abs_unavailable_rest_still_works(self):
        W.abs_mode = "deny"
        s = self.wait_state(lambda s: s["audiobook_downloads"] is not None and s["listening"] is None)
        self.assertIsNone(s["listening"])
        self.assertEqual(s["audiobook_downloads"], ABR)
        self.assertEqual(s["beefy"], "asleep")
        self.assertIn("local source unavailable: audiobookshelf: HTTP 401", self.sut.log())



class QbitThroughTraefik(Base):
    waker = "down"

    def test_qbit_counted_without_login_or_cookie(self):
        s = self.wait_state(lambda s: s["audiobook_downloads"] is not None)
        self.assertEqual(s["audiobook_downloads"], ABR)
        seen = W.qbit.seen()
        self.assertTrue(seen)
        for method, path, h in seen:
            self.assertEqual((method, path), ("GET", "/api/v2/torrents/info?category=abr"), "only the one read the Traefik route allows, never a login")
            self.assertNotIn("cookie", h)

    def test_qbit_route_refused_is_unavailable(self):
        W.qbit_mode = "deny"
        s = self.wait_state(lambda s: s["listening"] is not None)
        self.assertIsNone(s["audiobook_downloads"])
        self.assertEqual(s["listening"], {"sessions": 3})
        self.assertIn("qbittorrent: HTTP 403", self.sut.log())


if __name__ == "__main__":
    unittest.main()
