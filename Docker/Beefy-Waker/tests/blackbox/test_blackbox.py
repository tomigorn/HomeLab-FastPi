#!/usr/bin/env python3
"""Black-box tests for Beefy-Waker: real HTTP against the running program, fakes for beefy, Jellyfin, myStrom, Alertmanager and the WoL broadcast.

Runs inside a network-less container (run.sh), everything on loopback:
  127.0.0.1:9001  the waker (SUT), also the trusted proxy address
  127.0.0.2       beefy (TCP ports, Jellyfin fake on 8096)
  127.0.0.3:9     WoL sink (BEEFY_BROADCAST)
  127.0.0.4:80    myStrom plug fake
  127.0.0.5:9093  Alertmanager fake
  127.0.0.9       untrusted client source address
SUT is the command line: "python /app/waker.py" (old) or "/sut/beefy-waker" (new).
"""
import http.client
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

SUT = os.environ.get("SUT", "python /app/waker.py")
with open(os.environ.get("VERSION_FILE", "/app/VERSION")) as _f:
    VERSION = _f.read().strip()
WORK = "/tmp/bb"
MAC = "02:00:5e:10:20:30"
MAGIC = b"\xff" * 6 + bytes.fromhex(MAC.replace(":", "")) * 16
BEEFY = "127.0.0.2"
UNTRUSTED = "127.0.0.9"
PORT = 9001

BASE_ENV = {
    "WAKER_LISTEN_PORT": str(PORT), "WAKER_BIND": "127.0.0.1", "BEEFY_MAC": MAC,
    "BEEFY_BROADCAST": "127.0.0.3", "BEEFY_PROBE_HOST": BEEFY, "BEEFY_PROBE_PORT": "22",
    "WAKE_COUNTDOWN": "60", "BEEFY_SSH_USER": "buntu", "BEEFY_HISTORY_SINCE": "0",
    "WAKE_RETRY_INTERVAL": "1", "WAKE_RETRY_WINDOW": "4", "TRUSTED_PROXY": "127.0.0.1",
    "BEEFY_PLUG": "http://127.0.0.4", "ALERTMANAGER_URL": "http://127.0.0.5:9093",
    "WAKE_METRICS": WORK + "/textfile/beefy_wake.prom", "HOLD_SECONDS": "2", "HOLD_SLOTS": "2",
    "PUBLIC_INFO_CACHE": WORK + "/public-info.json", "JELLYFIN_PORT": "8096",
    "WAKE_STATE_FILE": WORK + "/power-cycle.state",
    "PATH": "/usr/local/bin:/usr/bin:/bin", "TZ": "UTC",
}

PUBLIC_INFO = b'{"LocalAddress":"http://192.0.2.10:8096","ServerName":"Test","Version":"10.11.0","Id":"abc123"}'

INITIAL_METRICS = """# HELP beefy_wake_phase Current wake recovery phase (1 = active).
# TYPE beefy_wake_phase gauge
beefy_wake_phase{phase="idle"} 1
beefy_wake_phase{phase="waking"} 0
beefy_wake_phase{phase="power_cycle"} 0
beefy_wake_phase{phase="retrying"} 0
beefy_wake_phase{phase="broken"} 0
# HELP beefy_wake_campaigns_total Wake campaigns started.
# TYPE beefy_wake_campaigns_total counter
beefy_wake_campaigns_total{signed_in="0"} 0
beefy_wake_campaigns_total{signed_in="1"} 0
# HELP beefy_wake_power_cycles_total Plug power-cycles done.
# TYPE beefy_wake_power_cycles_total counter
beefy_wake_power_cycles_total 0
# HELP beefy_wake_failures_total Times the broken phase was reached.
# TYPE beefy_wake_failures_total counter
beefy_wake_failures_total{reason="no_boot"} 0
beefy_wake_failures_total{reason="service_down"} 0
beefy_wake_failures_total{reason="plug_off"} 0
beefy_wake_failures_total{reason="plug_unreachable"} 0
# HELP beefy_wake_recoveries_total Times beefy came back after a power cycle or broken.
# TYPE beefy_wake_recoveries_total counter
beefy_wake_recoveries_total{after="power_cycle"} 0
beefy_wake_recoveries_total{after="broken"} 0
# HELP beefy_wake_background_total Lone background app requests that would not (observe) or did not (enforce) wake beefy.
# TYPE beefy_wake_background_total counter
beefy_wake_background_total{mode="observe"} 0
beefy_wake_background_total{mode="enforce"} 0
# HELP beefy_wake_last_event_timestamp_seconds Unix time of the last event.
# TYPE beefy_wake_last_event_timestamp_seconds gauge
"""

BROKEN_TITLE = "The server can't be started right now"


def wait_for(cond, timeout, step=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


# --- fakes -------------------------------------------------------------------
class TcpPort:
    """A port on fake beefy that accepts and closes connections (sshd, an app)."""

    def __init__(self, host, port):
        self.addr = (host, port)
        self.sock = None

    def start(self):
        if self.sock:
            return
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(self.addr)
        s.listen(64)
        self.sock = s
        threading.Thread(target=self._loop, args=(s,), daemon=True).start()

    def _loop(self, s):
        while True:
            try:
                c, _ = s.accept()
                c.close()
            except OSError:
                return

    def stop(self):
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()
            self.sock = None


class FakeHTTP:
    """Start/stop-able HTTP fake; subclasses implement handle(method, path, headers, body) -> (status, ctype, body)."""

    def __init__(self, host, port):
        self.addr = (host, port)
        self.srv = None
        self.requests = []
        self.lock = threading.Lock()

    def start(self):
        if self.srv:
            return
        fake = self

        class H(BaseHTTPRequestHandler):
            def _do(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                with fake.lock:
                    fake.requests.append((self.command, self.path, dict(self.headers), body))
                status, ctype, out = fake.handle(self.command, self.path, self.headers, body)
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            do_GET = do_POST = _do

            def log_message(self, *a):
                pass

        class S(ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.srv = S(self.addr, H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()
            self.srv = None

    def paths(self):
        with self.lock:
            return [p for _, p, _, _ in self.requests]


class Jellyfin(FakeHTTP):
    def __init__(self):
        super().__init__(BEEFY, 8096)
        self.reset()

    def reset(self):
        self.health = (200, b"Healthy")
        self.public = (200, PUBLIC_INFO)
        self.tokens = {"goodtoken123"}
        self.info_status = None
        self.delay = 0
        self.requests = []

    def handle(self, method, path, headers, body):
        if self.delay:
            time.sleep(self.delay)
        p = urlparse(path).path
        if p == "/health":
            return self.health[0], "text/plain", self.health[1]
        if p == "/System/Info/Public":
            return self.public[0], "application/json", self.public[1]
        if p == "/System/Info":
            if self.info_status:
                return self.info_status, "text/plain", b"err"
            m = re.search(r'Token="([^"]*)"', headers.get("Authorization") or "")
            if m and m.group(1) in self.tokens:
                return 200, "application/json", b'{"Id":"abc123"}'
            return 401, "text/plain", b""
        return 404, "text/plain", b""


class Plug(FakeHTTP):
    def __init__(self):
        super().__init__("127.0.0.4", 80)
        self.reset()

    def reset(self):
        self.relay = True
        self.power = 3.0
        self.switch_works = True
        self.requests = []

    def handle(self, method, path, headers, body):
        u = urlparse(path)
        if u.path == "/report":
            return 200, "application/json", json.dumps({"power": self.power, "relay": self.relay}).encode()
        if u.path == "/relay":
            state = parse_qs(u.query).get("state", [""])[0]
            if self.switch_works:
                self.relay = state == "1"
            return 200, "application/json", b""
        return 404, "text/plain", b""

    def relay_calls(self):
        return [p for p in self.paths() if p.startswith("/relay")]


class Alertmanager(FakeHTTP):
    def __init__(self):
        super().__init__("127.0.0.5", 9093)

    def handle(self, method, path, headers, body):
        return 200, "application/json", b""

    def alerts(self):
        with self.lock:
            return [(p, json.loads(b)) for m, p, _, b in self.requests if m == "POST"]


class WolSink:
    def __init__(self):
        self.packets = []
        self.lock = threading.Lock()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.3", 9))
        self.sock = s
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            data, _ = self.sock.recvfrom(2048)
            with self.lock:
                self.packets.append((time.monotonic(), data))

    def count(self):
        with self.lock:
            return len(self.packets)

    def reset(self):
        with self.lock:
            self.packets = []


# --- the program under test ----------------------------------------------------
class Sut:
    def __init__(self, env):
        self.env = dict(BASE_ENV, **env)
        self.lines = []
        self.lock = threading.Lock()
        self.proc = None

    def start(self, wait=True):
        self.proc = subprocess.Popen(shlex.split(SUT), env=self.env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, errors="replace")
        threading.Thread(target=self._read, daemon=True).start()
        if wait and not wait_for(self._listening, 10):
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
            for line in self.proc.stdout:
                with self.lock:
                    self.lines.append(line.rstrip("\n"))
        except ValueError:
            pass

    def log(self):
        with self.lock:
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


def req(method, path, headers=None, source=None, timeout=30, body=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout,
                                   source_address=(source, 0) if source else None)
    t = time.monotonic()
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, data, time.monotonic() - t


FAKES = {}


def setUpModule():
    FAKES["wol"] = WolSink()
    FAKES["jf"] = Jellyfin()
    FAKES["plug"] = Plug()
    FAKES["am"] = Alertmanager()
    FAKES["ssh"] = TcpPort(BEEFY, 22)
    FAKES["seerr"] = TcpPort(BEEFY, 5055)


class Base(unittest.TestCase):
    env = {}
    beefy_up = False
    jellyfin_up = False
    cache = None

    def setUp(self):
        shutil.rmtree(WORK, ignore_errors=True)
        os.makedirs(WORK + "/textfile")
        if self.cache is not None:
            with open(WORK + "/public-info.json", "wb") as f:
                f.write(self.cache)
        self.wol, self.jf, self.plug, self.am = FAKES["wol"], FAKES["jf"], FAKES["plug"], FAKES["am"]
        self.ssh, self.seerr = FAKES["ssh"], FAKES["seerr"]
        self.jf.reset()
        self.plug.reset()
        self.am.requests = []
        self.plug.start()
        self.am.start()
        (self.ssh.start if self.beefy_up else self.ssh.stop)()
        self.seerr.stop()
        (self.jf.start if self.jellyfin_up else self.jf.stop)()
        self.wol.reset()
        self.before_start()
        self.sut = Sut(self.env)
        self.sut.start()
        self.addCleanup(self.sut.stop)

    def before_start(self):
        pass

    def status(self, path="/status"):
        s, h, b, _ = req("GET", path)
        self.assertEqual(s, 200)
        return json.loads(b)

    def log_lines(self, needle):
        return [line for line in self.sut.log().splitlines() if needle in line]

    def wait_log(self, needle, timeout=2):
        wait_for(lambda: self.log_lines(needle), timeout)
        return self.log_lines(needle)

    def observe(self):
        wait_for(lambda: self.log_lines(" - observe {"), 1)
        out = []
        for line in self.log_lines(" - observe {"):
            out.append(json.loads(line.split(" - observe ", 1)[1]))
        return out

    def signed_in(self, user="alice"):
        return {"X-Authentik-Username": user}


# --- pages ---------------------------------------------------------------------
class Pages(Base):
    def test_root_page_is_manual_mode(self):
        s, h, b, _ = req("GET", "/")
        self.assertEqual((s, h["content-type"]), (200, "text/html; charset=utf-8"))
        self.assertEqual(int(h["content-length"]), len(b))
        t = b.decode()
        self.assertIn("const AUTOWAKE = false;", t)
        self.assertIn("const TOTAL = 60;", t)
        self.assertIn('<div class="count" id="count">~60s</div>', t)
        self.assertIn("<title>Wake beefy</title>", t)
        self.assertIn('<div class="ver">v%s</div>' % VERSION, t)
        self.assertIn("fetch('/history'", t)
        for ph in ("__COUNTDOWN__", "__AUTOWAKE__", "__VERSION__", "__BASE__"):
            self.assertNotIn(ph, t)
        self.assertEqual(self.wol.count(), 0)

    def test_wol_page_autowakes_in_browser_only(self):
        s, h, b, _ = req("GET", "/wol")
        self.assertEqual(s, 200)
        self.assertIn("const AUTOWAKE = true;", b.decode())
        time.sleep(0.3)
        self.assertEqual(self.wol.count(), 0)

    def test_trailing_slash_and_query_are_ignored(self):
        for p in ("/wol/", "/wol?x=1", "/status/", "/status?a=b"):
            s, _, _, _ = req("GET", p)
            self.assertEqual(s, 200, p)

    def test_unknown_path_is_404(self):
        for p in ("/nope", "/jf/nope", "/beefy-wake/", "/gatex", "/jf/history"):
            s, _, _, _ = req("GET", p)
            self.assertEqual(s, 404, p)

    def test_unsupported_methods_are_501(self):
        for m in ("HEAD", "PUT", "DELETE", "OPTIONS"):
            s, _, _, _ = req(m, "/status")
            self.assertEqual(s, 501, m)

    def test_jf_page_with_and_without_slash(self):
        for p in ("/jf", "/jf/"):
            s, h, b, _ = req("GET", p)
            self.assertEqual((s, h["content-type"]), (200, "text/html; charset=utf-8"), p)
            t = b.decode()
            self.assertIn("const BASE = '/beefy-wake/';", t)
            self.assertIn('<a id="retry" href="/beefy-wake/" hidden>Try again</a>', t)
            self.assertIn("let left = 60;", t)
            self.assertIn('<div class="ver">v%s</div>' % VERSION, t)
            self.assertIn("location.replace('/web/')", t)
        self.assertEqual(self.wol.count(), 0)

    def test_post_to_page_serves_page(self):
        s, _, b, _ = req("POST", "/", body=b"x")
        self.assertEqual(s, 200)
        self.assertIn(b"Wake beefy", b)

    def test_history_without_key(self):
        s, h, b, _ = req("GET", "/history")
        self.assertEqual((s, h["content-type"]), (503, "application/json"))
        self.assertEqual(json.loads(b), {"error": "history key not installed"})

    def test_initial_metrics_file(self):
        self.assertTrue(wait_for(lambda: os.path.exists(BASE_ENV["WAKE_METRICS"]), 3))
        time.sleep(0.2)
        with open(BASE_ENV["WAKE_METRICS"]) as f:
            self.assertEqual(f.read(), INITIAL_METRICS)
        self.assertEqual([n for n in os.listdir(WORK + "/textfile")], ["beefy_wake.prom"])

    def test_access_log_line(self):
        req("GET", "/status?x=1")
        self.assertTrue(wait_for(lambda: self.log_lines('127.0.0.1 - "GET /status?x=1 HTTP/1.1" 200 -'), 2), self.sut.log())

    def test_slow_client_does_not_block_others(self):
        s = socket.create_connection(("127.0.0.1", PORT))
        s.sendall(b"GET /status HTTP/1.1\r\n")
        t = time.monotonic()
        st, _, _, _ = req("GET", "/")
        self.assertEqual(st, 200)
        self.assertLess(time.monotonic() - t, 2)
        s.close()

    def test_many_parallel_requests(self):
        results = []

        def one():
            results.append(req("GET", "/")[0])

        ts = [threading.Thread(target=one) for _ in range(40)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(results, [200] * 40)


# --- /status and /wake ---------------------------------------------------------
class StatusAndWake(Base):
    def test_status_down_idle(self):
        s, h, b, _ = req("GET", "/status")
        self.assertEqual((s, h["content-type"]), (200, "application/json"))
        self.assertEqual(b, b'{"up": false, "phase": "idle", "seconds_left": null, "reason": ""}')

    def test_status_up(self):
        self.ssh.start()
        self.assertEqual(self.status(), {"up": True, "phase": "idle", "seconds_left": None, "reason": ""})

    def test_wake_get_is_405(self):
        s, h, b, _ = req("GET", "/wake", {"X-Wake": "1"})
        self.assertEqual((s, h["content-type"], b), (405, "application/json", b'{"error": "POST only"}'))
        self.assertEqual(self.wol.count(), 0)

    def test_wake_csrf_refusals(self):
        cases = [{}, {"X-Wake": "2"}, {"X-Wake": "1", "Origin": "https://evil.example.com"},
                 {"X-Wake": "1", "Origin": "null"}, {"X-Wake": "1", "Origin": "http://127.0.0.1:9001.evil"}]
        for hd in cases:
            s, h, b, _ = req("POST", "/wake", hd)
            self.assertEqual((s, b), (403, b'{"error": "needs X-Wake: 1 from this origin"}'), hd)
        self.assertEqual(self.wol.count(), 0)

    def test_wake_without_origin_sends_magic_packet(self):
        s, h, b, _ = req("POST", "/wake", {"X-Wake": "1"})
        self.assertEqual((s, h["content-type"], b), (200, "application/json", b'{"sent": true}'))
        self.assertTrue(wait_for(lambda: self.wol.count() >= 1, 2))
        self.assertEqual(self.wol.packets[0][1], MAGIC)
        self.assertTrue(self.wait_log("manual wake -> sent WoL to %s via 127.0.0.3" % MAC))

    def test_wake_same_origin_case_insensitive(self):
        s, _, b, _ = req("POST", "/wake", {"X-Wake": "1", "Origin": "HTTP://127.0.0.1:9001"})
        self.assertEqual((s, b), (200, b'{"sent": true}'))

    def test_wake_campaign_resends_then_gives_up(self):
        req("POST", "/wake", {"X-Wake": "1"})
        st = self.status()
        self.assertEqual(st, {"up": False, "phase": "waking", "seconds_left": None, "reason": ""})
        self.assertTrue(wait_for(lambda: self.wol.count() >= 3, 4), self.wol.count())
        self.assertTrue(wait_for(lambda: self.status()["phase"] == "idle", 6))
        n = self.wol.count()
        time.sleep(1.5)
        self.assertEqual(self.wol.count(), n)
        self.assertEqual(self.plug.requests, [])

    def test_second_wake_joins_campaign(self):
        req("POST", "/wake", {"X-Wake": "1"})
        req("POST", "/wake", {"X-Wake": "1"})
        self.assertTrue(wait_for(lambda: self.wol.count() >= 2, 1))
        time.sleep(0.3)
        with open(BASE_ENV["WAKE_METRICS"]) as f:
            self.assertIn('beefy_wake_campaigns_total{signed_in="0"} 1\n', f.read())

    def test_campaign_metrics(self):
        req("POST", "/wake", {"X-Wake": "1"})
        time.sleep(0.3)
        with open(BASE_ENV["WAKE_METRICS"]) as f:
            t = f.read()
        self.assertIn('beefy_wake_phase{phase="waking"} 1\n', t)
        self.assertIn('beefy_wake_campaigns_total{signed_in="0"} 1\n', t)
        self.assertRegex(t, r'beefy_wake_last_event_timestamp_seconds\{event="campaign"\} \d+\.\d+\n$')

    def test_campaign_ends_when_beefy_answers(self):
        req("POST", "/wake", {"X-Wake": "1"})
        self.ssh.start()
        self.assertTrue(wait_for(lambda: self.status()["phase"] == "idle", 8))

    def test_lan_wake_never_arms_even_with_user_header(self):
        req("POST", "/wake", dict(self.signed_in(), **{"X-Wake": "1"}))
        self.assertIsNone(self.status()["seconds_left"])


class WolFailure(Base):
    env = {"BEEFY_BROADCAST": "256.1.1.1"}

    def test_failed_send_reports_false(self):
        s, _, b, _ = req("POST", "/wake", {"X-Wake": "1"})
        self.assertEqual((s, b), (200, b'{"sent": false}'))
        self.assertTrue(self.wait_log("WoL send failed: "))
        self.assertEqual(self.status()["phase"], "idle")

    def test_gate_still_answers_503(self):
        s, h, b, _ = req("GET", "/gate")
        self.assertEqual(s, 503)
        self.assertIn(b"Waking up beefy...", b)


class Startup(unittest.TestCase):
    def run_bad(self, env):
        e = dict(BASE_ENV, **env)
        e = {k: v for k, v in e.items() if v is not None}
        p = subprocess.run(shlex.split(SUT), env=e, capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout + p.stderr

    def test_missing_mac(self):
        rc, out = self.run_bad({"BEEFY_MAC": None})
        self.assertNotEqual(rc, 0)
        self.assertIn("missing required env: BEEFY_MAC", out)

    def test_missing_both(self):
        rc, out = self.run_bad({"BEEFY_MAC": "", "BEEFY_PROBE_HOST": ""})
        self.assertNotEqual(rc, 0)
        self.assertIn("missing required env: BEEFY_MAC, BEEFY_PROBE_HOST", out)

    def test_invalid_mac(self):
        rc, out = self.run_bad({"BEEFY_MAC": "02:00:5e:10:20"})
        self.assertNotEqual(rc, 0)

    def test_banner(self):
        sut = Sut({})
        sut.start()
        try:
            self.assertTrue(wait_for(lambda: "beefy-waker listening on 127.0.0.1:9001 - page=/ gate=/gate, wake %s via 127.0.0.3, probe 127.0.0.2:22" % MAC in sut.log(), 2), sut.log())
        finally:
            sut.stop()


# --- /gate without policy ------------------------------------------------------
class Gate(Base):
    def test_up_passes(self):
        self.ssh.start()
        s, h, b, _ = req("GET", "/gate")
        self.assertEqual((s, h["content-type"], b), (200, "text/plain", b""))
        self.assertEqual(self.wol.count(), 0)

    def test_down_wakes_and_serves_page(self):
        s, h, b, _ = req("GET", "/gate", {"Accept": "text/html"})
        self.assertEqual((s, h["content-type"], h.get("retry-after")), (503, "text/html; charset=utf-8", "5"))
        t = b.decode()
        self.assertIn('<meta http-equiv="refresh" content="5">', t)
        self.assertIn("<title>Waking up beefy...</title>", t)
        self.assertIn('<div class="spin"></div>', t)
        self.assertIn("<p>A magic packet is on its way. This page refreshes automatically.</p>", t)
        self.assertIn("<p>The server should be ready in under a minute.</p>", t)
        self.assertTrue(wait_for(lambda: self.wol.count() >= 1, 2))
        self.assertTrue(self.wait_log("beefy down (127.0.0.2:22) - sent WoL to %s via 127.0.0.3" % MAC))

    def test_port_override(self):
        self.seerr.start()
        s, _, _, _ = req("GET", "/gate?port=5055")
        self.assertEqual(s, 200)
        self.seerr.stop()
        self.ssh.start()
        s, _, _, _ = req("GET", "/gate?port=5055")
        self.assertEqual(s, 503)
        self.assertTrue(self.wait_log("beefy down (127.0.0.2:5055)"))

    def test_bad_port_falls_back_to_default(self):
        self.ssh.start()
        for q in ("port=abc", "port=0", "port=70000", "port=-1", "port=", "host=192.0.2.1&port=x"):
            s, _, _, _ = req("GET", "/gate?" + q)
            self.assertEqual(s, 200, q)
        self.assertEqual(self.wol.count(), 0)

    def test_host_override_ignored(self):
        s, _, _, _ = req("GET", "/gate?host=127.0.0.1&port=9001")
        self.assertEqual(s, 503)

    def test_signed_in_flag_and_header_arms(self):
        s, _, _, _ = req("GET", "/gate?port=5055&signed_in=1", self.signed_in())
        self.assertEqual(s, 503)
        st = self.status()
        self.assertEqual(st["phase"], "waking")
        self.assertIsInstance(st["seconds_left"], int)
        self.assertTrue(115 <= st["seconds_left"] <= 120, st)
        time.sleep(0.3)
        with open(BASE_ENV["WAKE_METRICS"]) as f:
            self.assertIn('beefy_wake_campaigns_total{signed_in="1"} 1\n', f.read())

    def test_flag_without_header_does_not_arm(self):
        req("GET", "/gate?port=5055&signed_in=1")
        req("GET", "/gate?port=5055&signed_in=1", {"X-Authentik-Username": "   "})
        self.assertIsNone(self.status()["seconds_left"])

    def test_header_without_flag_does_not_arm(self):
        req("GET", "/gate?port=5055", self.signed_in())
        req("GET", "/gate?port=5055&signed_in=yes", self.signed_in())
        self.assertIsNone(self.status()["seconds_left"])

    def test_untrusted_peer_does_not_arm(self):
        req("GET", "/gate?port=5055&signed_in=1", self.signed_in(), source=UNTRUSTED)
        st = self.status()
        self.assertEqual(st["phase"], "waking")
        self.assertIsNone(st["seconds_left"])

    def test_gate_post_works_too(self):
        self.ssh.start()
        s, _, _, _ = req("POST", "/gate")
        self.assertEqual(s, 200)


# --- /gate?policy=jellyfin -----------------------------------------------------
JF = "/gate?port=8096&policy=jellyfin"
APP = {"Accept": "application/json", "Authorization": 'MediaBrowser Client="Jellyfin Android TV", Device="tv", Token="goodtoken123"',
       "X-Forwarded-Uri": "/System/Info?api_key=supersecretvalue", "X-Forwarded-Method": "GET"}
BROWSER = {"Accept": "text/html,application/xhtml+xml", "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
           "User-Agent": "Mozilla/5.0 Test", "X-Forwarded-Uri": "/web/", "CF-Connecting-IP": "198.51.100.7"}


class JellyfinGate(Base):
    def test_healthy_passes_without_observe(self):
        self.jf.start()
        s, h, b, _ = req("GET", JF, APP)
        self.assertEqual((s, b), (200, b""))
        self.assertEqual(self.observe(), [])
        self.assertEqual(self.wol.count(), 0)

    def test_healthy_system_info_public_is_observed(self):
        self.jf.start()
        req("GET", JF, {"X-Forwarded-Uri": "//system/info/PUBLIC?x=1"})
        obs = self.observe()
        self.assertEqual(len(obs), 1)
        self.assertEqual((obs[0]["up"], obs[0]["decision"], obs[0]["path"]), (True, "pass", "//system/info/PUBLIC"))

    def test_healthy_answer_cached_5s(self):
        self.jf.start()
        req("GET", JF)
        req("GET", JF)
        req("GET", JF)
        self.assertEqual(self.jf.paths().count("/health"), 1)

    def test_unhealthy_never_cached(self):
        self.ssh.start()
        self.jf.start()
        self.jf.health = (503, b"Unhealthy")
        s1 = req("GET", JF, BROWSER)[0]
        self.jf.health = (200, b"Healthy")
        s2 = req("GET", JF, BROWSER)[0]
        self.assertEqual((s1, s2), (503, 200))

    def test_200_but_not_healthy_text_is_not_ready(self):
        self.ssh.start()
        self.jf.start()
        self.jf.health = (200, b"Degraded")
        s, _, _, _ = req("GET", JF, BROWSER)
        self.assertEqual(s, 503)

    def test_browser_asleep_gets_signin_page_no_wake(self):
        s, h, b, _ = req("GET", JF, BROWSER)
        self.assertEqual((s, h["content-type"]), (503, "text/html; charset=utf-8"))
        self.assertNotIn("retry-after", h)
        t = b.decode()
        self.assertIn("<title>Jellyfin is asleep</title>", t)
        self.assertIn('<a class="btn" href="/beefy-wake/">Sign in to start it</a>', t)
        self.assertIn('<div class="moon">&#128164;</div>', t)
        self.assertNotIn("refresh", t)
        time.sleep(0.3)
        self.assertEqual(self.wol.count(), 0)
        self.assertEqual(self.status()["phase"], "idle")

    def test_browser_subresource_no_wake(self):
        for dest in ("image", "script", "style", "font"):
            s, _, b, _ = req("GET", JF, {"Accept": "*/*", "Sec-Fetch-Dest": dest})
            self.assertEqual(s, 503)
            self.assertIn(b"Jellyfin is asleep", b)
        self.assertEqual(self.wol.count(), 0)

    def test_app_wakes_and_is_held_then_503(self):
        s, h, b, el = req("GET", JF, APP)
        self.assertEqual((s, h.get("retry-after")), (503, "5"))
        self.assertIn(b"Waking up beefy...", b)
        self.assertTrue(0.8 <= el <= 3.5, el)
        self.assertGreaterEqual(self.wol.count(), 1)
        self.assertTrue(self.wait_log("beefy down (127.0.0.2:8096) - sent WoL to"))
        self.assertIsNone(self.status()["seconds_left"])

    def test_scanner_without_accept_wakes(self):
        s, _, _, _ = req("GET", JF, {"Sec-Fetch-Dest": "empty"})
        self.assertEqual(s, 503)
        self.assertGreaterEqual(self.wol.count(), 1)

    def test_held_app_passes_when_ready(self):
        self.jf.health = (503, b"Starting")
        self.jf.start()

        def later():
            time.sleep(0.6)
            self.jf.health = (200, b"Healthy")
        threading.Thread(target=later).start()
        s, _, b, el = req("GET", JF, APP)
        self.assertEqual((s, b), (200, b""))
        self.assertLess(el, 2.5)
        obs = self.observe()
        self.assertEqual(obs[0]["decision"], "wake")

    def test_starting_browser_gets_waking_page_immediately(self):
        self.ssh.start()
        s, h, b, el = req("GET", JF, BROWSER)
        self.assertEqual((s, h.get("retry-after")), (503, "5"))
        self.assertIn(b"Waking up beefy...", b)
        self.assertLess(el, 1.0)
        self.assertEqual(self.wol.count(), 0)

    def test_starting_app_is_held_without_wake(self):
        self.ssh.start()
        s, _, _, el = req("GET", JF, APP)
        self.assertEqual(s, 503)
        self.assertGreaterEqual(el, 0.8)
        self.assertEqual(self.wol.count(), 0)
        self.assertEqual(self.observe()[0]["decision"], "starting")

    def test_during_campaign_browser_is_starting(self):
        req("POST", "/wake", {"X-Wake": "1"})
        n = self.wol.count()
        s, _, b, _ = req("GET", JF, BROWSER)
        self.assertEqual(s, 503)
        self.assertIn(b"Waking up beefy...", b)
        self.assertEqual(self.observe()[0]["decision"], "starting")

    def test_signed_in_never_arms_jellyfin_gate(self):
        req("GET", JF + "&signed_in=1", dict(APP, **self.signed_in()))
        self.assertIsNone(self.status()["seconds_left"])

    def test_no_free_slot_means_immediate_503(self):
        results = []

        def one():
            results.append(req("GET", JF, APP))

        ts = [threading.Thread(target=one) for _ in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        fast = [r for r in results if r[3] < 0.8]
        self.assertGreaterEqual(len(fast), 2, [round(r[3], 2) for r in results])
        self.assertTrue(all(r[0] == 503 for r in results))

    def test_observe_record_fields(self):
        req("GET", JF, dict(APP, **{"X-Forwarded-Uri": "/Items?api_key=supersecretvalue&Fields=a&b=", "CF-Connecting-IP": "198.51.100.7",
                                     "X-Real-Ip": "203.0.113.1", "User-Agent": "JellyfinAndroid/1.0",
                                     "X-Emby-Token": "x", "Sec-Fetch-Mode": "cors"}))
        obs = self.observe()
        self.assertEqual(len(obs), 1)
        rec = obs[0]
        self.assertEqual(sorted(rec), sorted(["up", "decision", "method", "path", "query_keys", "auth_mediabrowser", "x_emby_authorization",
                                              "x_emby_token", "x_mediabrowser_token", "client", "ua", "accept", "sec_fetch_mode",
                                              "sec_fetch_dest", "ip", "held", "class"]))
        self.assertEqual(rec["up"], False)
        self.assertEqual(rec["decision"], "wake")
        self.assertEqual(rec["class"], "foreground")
        self.assertEqual(rec["method"], "GET")
        self.assertEqual(rec["path"], "/Items")
        self.assertEqual(rec["query_keys"], ["Fields", "api_key", "b"])
        self.assertEqual(rec["auth_mediabrowser"], True)
        self.assertEqual(rec["x_emby_authorization"], False)
        self.assertEqual(rec["x_emby_token"], True)
        self.assertEqual(rec["x_mediabrowser_token"], False)
        self.assertEqual(rec["client"], "Jellyfin Android TV")
        self.assertEqual(rec["ua"], "JellyfinAndroid/1.0")
        self.assertEqual(rec["accept"], "application/json")
        self.assertEqual(rec["sec_fetch_mode"], "cors")
        self.assertEqual(rec["sec_fetch_dest"], "")
        self.assertEqual(rec["ip"], "198.51.100.7")
        self.assertIsInstance(rec["held"], float)
        self.assertTrue(0.8 <= rec["held"] <= 2.5, rec["held"])

    def test_observe_line_is_sorted_python_style_json(self):
        req("GET", JF, BROWSER)
        line = self.log_lines(" - observe {")[0]
        self.assertTrue(line.startswith("127.0.0.1 - observe {\"accept\": \"text/html,application/xhtml+xml\", \"auth_mediabrowser\": false, "), line)
        self.assertIn('"held": 0.0, "ip": "198.51.100.7", "method": "", "path": "/web/", "query_keys": [], ', line)

    def test_observe_non_ascii_is_escaped(self):
        req("GET", JF, dict(BROWSER, **{"User-Agent": "Gr\u00fc\u00dfe".encode().decode("latin-1")}))
        line = self.log_lines(" - observe {")[0]
        self.assertTrue(line.isascii(), line)

    def test_observe_never_logs_tokens(self):
        req("GET", JF, dict(APP, **{"X-Emby-Authorization": 'MediaBrowser Client="Web", Token="anothersecret99"',
                                     "X-Forwarded-Uri": "/x?ApiKey=supersecretvalue"}))
        log = self.sut.log()
        self.assertNotIn("supersecretvalue", log)
        self.assertNotIn("goodtoken123", log)
        self.assertNotIn("anothersecret99", log)

    def test_observe_bounds(self):
        q = "&".join("k%02d=v" % i for i in range(30)) + "&" + "z" * 60 + "=1"
        req("GET", JF, {"X-Forwarded-Uri": "/p?" + q, "User-Agent": "u" * 300, "Accept": "a" * 100})
        rec = self.observe()[0]
        self.assertEqual(len(rec["query_keys"]), 20)
        self.assertEqual(rec["query_keys"][0], "k00")
        self.assertEqual(len(rec["ua"]), 160)
        self.assertEqual(len(rec["accept"]), 80)
        q = "&".join("k%02d=v" % i for i in range(60))
        req("GET", JF, {"X-Forwarded-Uri": "/p?" + q})
        self.assertEqual(self.observe()[1]["query_keys"], ["<too many>"])

    def test_observe_emby_authorization_client(self):
        req("GET", JF, {"X-Emby-Authorization": 'MediaBrowser Client="Jellyfin Web", Token="tok12345678"', "X-Forwarded-For": "203.0.113.5, 10.0.0.1"})
        rec = self.observe()[0]
        self.assertEqual((rec["client"], rec["x_emby_authorization"], rec["auth_mediabrowser"], rec["ip"]), ("Jellyfin Web", True, False, "203.0.113.5"))


# --- /jf/status, /jf/wake ---------------------------------------------------
class JfEndpoints(Base):
    def test_jf_status_uses_health(self):
        self.ssh.start()
        self.assertEqual(self.status("/jf/status"), {"up": False, "phase": "idle", "seconds_left": None, "reason": ""})
        self.jf.start()
        self.assertEqual(self.status("/jf/status")["up"], True)
        self.assertIn("/health", self.jf.paths())

    def test_jf_wake_get_405_and_csrf(self):
        self.assertEqual(req("GET", "/jf/wake", {"X-Wake": "1"})[0], 405)
        self.assertEqual(req("POST", "/jf/wake")[0], 403)
        self.assertEqual(req("POST", "/jf/wake", {"X-Wake": "1", "Origin": "https://evil.example.com", "Host": "jellyfin.example.com"})[0], 403)
        self.assertEqual(self.wol.count(), 0)

    def test_jf_wake_signed_in_arms(self):
        s, _, b, _ = req("POST", "/jf/wake", dict(self.signed_in(), **{"X-Wake": "1", "Origin": "https://jellyfin.example.com", "Host": "jellyfin.example.com"}))
        self.assertEqual((s, b), (200, b'{"sent": true}'))
        self.assertTrue(self.wait_log("jf wake by alice -> sent WoL to %s via 127.0.0.3" % MAC))
        self.assertIsInstance(self.status()["seconds_left"], int)

    def test_jf_wake_untrusted_peer(self):
        s, _, b, _ = req("POST", "/jf/wake", dict(self.signed_in(), **{"X-Wake": "1"}), source=UNTRUSTED)
        self.assertEqual((s, b), (200, b'{"sent": true}'))
        self.assertTrue(self.wait_log("127.0.0.9 - jf wake by ? -> sent WoL"))
        self.assertIsNone(self.status()["seconds_left"])

    def test_jf_wake_user_truncated(self):
        req("POST", "/jf/wake", {"X-Wake": "1", "X-Authentik-Username": "  " + "u" * 100 + "  "})
        self.assertTrue(self.wait_log("jf wake by %s -> " % ("u" * 64)))


# --- /jf/public-info --------------------------------------------------------
MB = {"Authorization": 'MediaBrowser Client="Jellyfin Android TV", Device="tv", DeviceId="1", Version="1"'}


class PublicInfo(Base):
    def test_healthy_relays_and_caches(self):
        self.jf.start()
        s, h, b, _ = req("GET", "/jf/public-info")
        self.assertEqual((s, h["content-type"], h.get("access-control-allow-origin"), b), (200, "application/json", "*", PUBLIC_INFO))
        with open(WORK + "/public-info.json", "rb") as f:
            self.assertEqual(f.read(), PUBLIC_INFO)
        rec = self.observe()[0]
        self.assertEqual((rec["path"], rec["method"], rec["decision"], rec["cached"], rec["held"], rec["query_keys"]),
                         ("/System/Info/Public", "GET", "pass", False, 0.0, []))

    def test_query_keys_come_from_request(self):
        self.jf.start()
        req("GET", "/jf/public-info?b=1&a=2")
        self.assertEqual(self.observe()[0]["query_keys"], ["a", "b"])

    def test_bad_answers_not_cached(self):
        self.jf.start()
        for st, body in ((200, b"[1,2]"), (200, b"{\"NoId\":1}"), (200, b"not json"), (500, PUBLIC_INFO), (200, b"{\"Id\":\"" + b"x" * 70000 + b"\"}")):
            self.jf.public = (st, body)
            s, _, _, _ = req("GET", "/jf/public-info")
            self.assertEqual(s, 503, (st, body[:20]))
        self.assertFalse(os.path.exists(WORK + "/public-info.json"))

    def test_down_mediabrowser_without_cache_is_held_then_503(self):
        s, h, b, el = req("GET", "/jf/public-info", MB)
        self.assertEqual((s, h.get("retry-after")), (503, "5"))
        self.assertIn(b"Waking up beefy...", b)
        self.assertTrue(0.8 <= el <= 3.5, el)
        self.assertGreaterEqual(self.wol.count(), 1)
        self.assertTrue(self.wait_log("beefy down (127.0.0.2:8096) - sent WoL to"))

    def test_down_browser_gets_signin_no_wake(self):
        s, _, b, el = req("GET", "/jf/public-info", BROWSER)
        self.assertEqual(s, 503)
        self.assertIn(b"Jellyfin is asleep", b)
        self.assertEqual(self.wol.count(), 0)

    def test_down_held_then_relays_when_ready(self):
        self.jf.health = (503, b"Starting")
        self.jf.start()

        def later():
            time.sleep(0.6)
            self.jf.health = (200, b"Healthy")
        threading.Thread(target=later).start()
        s, _, b, _ = req("GET", "/jf/public-info", MB)
        self.assertEqual((s, b), (200, PUBLIC_INFO))
        self.assertTrue(os.path.exists(WORK + "/public-info.json"))

    def test_public_info_never_arms(self):
        req("GET", "/jf/public-info", dict(MB, **self.signed_in()))
        self.assertIsNone(self.status()["seconds_left"])


class PublicInfoCached(Base):
    cache = b'{"Id":"cached1","ServerName":"Cached"}'

    def test_cache_file_loaded_and_served_to_native_app(self):
        s, h, b, el = req("GET", "/jf/public-info", MB)
        self.assertEqual((s, b, h.get("access-control-allow-origin")), (200, self.cache, "*"))
        self.assertTrue(0.8 <= el <= 3.5, el)
        rec = self.observe()[0]
        self.assertEqual((rec["cached"], rec["decision"]), (True, "wake"))

    def test_cache_not_served_without_mediabrowser_header(self):
        s, _, b, _ = req("GET", "/jf/public-info", {"Accept": "application/json"})
        self.assertEqual(s, 503)
        self.assertIn(b"Waking up beefy...", b)

    def test_starting_native_app_held_then_cache(self):
        self.ssh.start()
        s, _, b, el = req("GET", "/jf/public-info", MB)
        self.assertEqual((s, b), (200, self.cache))
        self.assertEqual(self.wol.count(), 0)

    def test_pass_but_relay_fails_serves_cache(self):
        self.jf.start()
        self.jf.public = (500, b"")
        s, _, b, _ = req("GET", "/jf/public-info", MB)
        self.assertEqual((s, b), (200, self.cache))
        self.assertEqual(self.observe()[0]["cached"], True)

    def test_new_answer_replaces_cache(self):
        self.jf.start()
        req("GET", "/jf/public-info")
        with open(WORK + "/public-info.json", "rb") as f:
            self.assertEqual(f.read(), PUBLIC_INFO)
        self.jf.stop()
        s, _, b, _ = req("GET", "/jf/public-info", MB)
        self.assertEqual((s, b), (200, PUBLIC_INFO))


class PublicInfoBadCache(Base):
    cache = b"not json"

    def test_invalid_cache_file_ignored(self):
        s, _, _, _ = req("GET", "/jf/public-info", MB)
        self.assertEqual(s, 503)


# --- /stream-auth -----------------------------------------------------------
class StreamAuth(Base):
    jellyfin_up = True

    def sa(self, headers):
        return req("GET", "/stream-auth", dict({"X-Forwarded-Uri": "/Videos/1/stream?static=true"}, **headers))

    def test_options_preflight_passes(self):
        s, _, b, _ = self.sa({"X-Forwarded-Method": "options"})
        self.assertEqual((s, b), (200, b""))

    def test_no_token_401_without_asking_jellyfin(self):
        s, h, b, _ = self.sa({})
        self.assertEqual((s, h["content-type"], b), (401, "text/plain", b"unauthorized"))
        self.assertNotIn("/System/Info", self.jf.paths())

    def test_valid_token_each_place(self):
        places = [{"Authorization": 'MediaBrowser Client="x", Token="goodtoken123"'},
                  {"X-Emby-Authorization": 'MediaBrowser Token="goodtoken123", Client="x"'},
                  {"X-Emby-Token": "goodtoken123"}, {"X-MediaBrowser-Token": "goodtoken123"},
                  {"X-Forwarded-Uri": "/Videos/1/stream?static=true&api_key=goodtoken123"},
                  {"X-Forwarded-Uri": "/Videos/1/stream?ApiKey=goodtoken123"},
                  {"X-Forwarded-Uri": "/Videos/1/stream?APIKEY=goodtoken123"}]
        for hd in places:
            s, _, _, _ = self.sa(hd)
            self.assertEqual(s, 200, hd)
        reqs = [h for m, p, h, b in self.jf.requests if p == "/System/Info"]
        self.assertEqual(len(reqs), 1)
        self.assertEqual({k.lower(): v for k, v in reqs[0].items()}.get("authorization"), 'MediaBrowser Token="goodtoken123"')

    def test_wrong_token_401_and_not_cached(self):
        self.assertEqual(self.sa({"X-Emby-Token": "wrongtoken99"})[0], 401)
        self.assertEqual(self.sa({"X-Emby-Token": "wrongtoken99"})[0], 401)
        self.assertEqual(self.jf.paths().count("/System/Info"), 2)

    def test_malformed_token_401_without_jellyfin(self):
        for hd in ({"X-Emby-Token": 'bad"x'}, {"X-Emby-Token": "short"}, {"X-Emby-Token": "a b c d e f g h"},
                   {"Authorization": 'MediaBrowser Token=""'}, {"X-Emby-Token": "x" * 257}):
            self.assertEqual(self.sa(hd)[0], 401, hd)
        self.assertNotIn("/System/Info", self.jf.paths())

    def test_403_from_jellyfin_is_401(self):
        self.jf.info_status = 403
        self.assertEqual(self.sa({"X-Emby-Token": "goodtoken123"})[0], 401)

    def test_jellyfin_error_is_503(self):
        self.jf.info_status = 500
        s, h, b, _ = self.sa({"X-Emby-Token": "goodtoken123"})
        self.assertEqual((s, h.get("retry-after"), b), (503, "5", b"jellyfin unavailable"))

    def test_jellyfin_down_is_503(self):
        self.jf.stop()
        s, _, b, _ = self.sa({"X-Emby-Token": "goodtoken123"})
        self.assertEqual((s, b), (503, b"jellyfin unavailable"))

    def test_valid_token_cached(self):
        self.assertEqual(self.sa({"X-Emby-Token": "goodtoken123"})[0], 200)
        self.jf.stop()
        self.assertEqual(self.sa({"X-Emby-Token": "goodtoken123"})[0], 200)

    def test_first_token_header_wins(self):
        s, _, _, _ = self.sa({"Authorization": 'MediaBrowser Token="wrongtoken99"', "X-Emby-Token": "goodtoken123"})
        self.assertEqual(s, 401)

    def test_token_never_logged(self):
        self.sa({"X-Emby-Token": "goodtoken123"})
        self.sa({"X-Forwarded-Uri": "/Videos/1/stream?api_key=goodtoken123"})
        self.assertNotIn("goodtoken123", "\n".join(l for l in self.sut.log().splitlines() if "GET /stream-auth" not in l))


# --- wake recovery (slow: real 15 s plug-off and 5 s settle) -------------------
REC = {"WAKE_T1": "2", "WAKE_T2": "3"}
SIGNED_JF = {"X-Wake": "1", "X-Authentik-Username": "alice"}


def metrics():
    with open(BASE_ENV["WAKE_METRICS"]) as f:
        return f.read()


class Recovery(Base):
    env = REC

    def phase(self):
        return self.status()["phase"]

    def test_no_boot_power_cycle_then_broken_then_recovered(self):
        req("POST", "/jf/wake", SIGNED_JF)
        self.assertTrue(wait_for(lambda: self.phase() == "power_cycle", 6))
        st = self.status()
        self.assertTrue(15 <= st["seconds_left"] <= 18, st)
        self.assertEqual(self.plug.relay_calls(), ["/relay?state=0"])
        self.assertTrue(wait_for(lambda: self.phase() == "broken", 30))
        self.assertEqual(self.plug.relay_calls(), ["/relay?state=0", "/relay?state=1"])
        self.assertEqual(self.status(), {"up": False, "phase": "broken", "seconds_left": None, "reason": "no_boot"})
        alerts = self.am.alerts()
        self.assertEqual(len(alerts), 1)
        path, body = alerts[0]
        self.assertEqual(path, "/api/v2/alerts")
        a = body[0]
        self.assertEqual({k: v for k, v in a["labels"].items() if k != "at"},
                         {"alertname": "BeefyWakeFailed", "host": "beefy", "severity": "critical", "source": "beefy-waker"})
        self.assertRegex(a["labels"]["at"], r"^\d{14}$")
        self.assertEqual(a["annotations"]["summary"], "Beefy wake failed: beefy did not boot after a power cycle")
        self.assertRegex(a["annotations"]["details"], r"^user=alice service=Jellyfin seconds_since_start=2[0-9] plug_power=3\.0W$")
        self.assertTrue(a["annotations"]["description"].startswith("Check beefy's screen and the beefy plug in Home Assistant"))
        self.assertRegex(a["annotations"]["time"], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")
        self.assertRegex(a["startsAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        t0 = time.strptime(a["startsAt"], "%Y-%m-%dT%H:%M:%SZ")
        t1 = time.strptime(a["endsAt"], "%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(time.mktime(t1) - time.mktime(t0), 3600)
        wait_for(lambda: 'beefy_wake_failures_total{reason="no_boot"} 1' in metrics(), 2)
        m = metrics()
        for line in ('beefy_wake_phase{phase="broken"} 1', 'beefy_wake_campaigns_total{signed_in="1"} 1',
                     "beefy_wake_power_cycles_total 1", 'beefy_wake_failures_total{reason="no_boot"} 1'):
            self.assertIn(line + "\n", m)
        events = re.findall(r'event="(\w+)"', m)
        self.assertEqual(events, ["campaign", "failure", "power_cycle"])
        # broken pages
        s, h, b, _ = req("GET", "/gate")
        t = b.decode()
        self.assertIn('<meta http-equiv="refresh" content="30">', t)
        self.assertIn("<h1>%s</h1>" % BROKEN_TITLE, t)
        self.assertNotIn('class="spin"', t)
        s, h, b, _ = req("GET", JF, BROWSER)
        self.assertIn(("<h1>%s</h1>" % BROKEN_TITLE).encode(), b)
        self.assertNotIn(b"Sign in to start it", b)
        # a wake while broken changes nothing
        n = self.wol.count()
        req("POST", "/jf/wake", SIGNED_JF)
        self.assertEqual(self.wol.count(), n + 1)
        self.assertEqual(self.phase(), "broken")
        # beefy comes back: the 30 s watch sees it
        self.ssh.start()
        self.assertTrue(wait_for(lambda: self.phase() == "idle", 35))
        alerts = self.am.alerts()
        self.assertEqual(len(alerts), 2)
        a = alerts[1][1][0]
        self.assertEqual((a["labels"]["alertname"], a["labels"]["severity"], a["annotations"]["summary"]),
                         ("BeefyWakeRecovered", "info", "Beefy is back after broken"))
        self.assertTrue(wait_for(lambda: 'beefy_wake_recoveries_total{after="broken"} 1\n' in metrics(), 2), metrics())

    def test_recovered_after_power_cycle_then_latched(self):
        req("GET", "/gate?port=5055&signed_in=1", self.signed_in("bob"))
        self.assertTrue(wait_for(lambda: self.plug.relay_calls() == ["/relay?state=0"], 6))
        self.ssh.start()
        self.seerr.start()
        self.assertTrue(wait_for(lambda: self.phase() == "idle", 30))
        self.assertEqual(self.plug.relay_calls(), ["/relay?state=0", "/relay?state=1"])
        a = self.am.alerts()[0][1][0]
        self.assertEqual((a["labels"]["alertname"], a["annotations"]["summary"]), ("BeefyWakeRecovered", "Beefy is back after power cycle"))
        self.assertRegex(a["annotations"]["details"], r"^user=bob service=Seerr seconds_since_start=\d+ plug_power=3\.0W$")
        self.assertTrue(wait_for(lambda: 'beefy_wake_recoveries_total{after="power_cycle"} 1\n' in metrics(), 2), metrics())
        self.assertIn("beefy_wake_power_cycles_total 1\n", metrics())
        # second failure inside the 6 h latch: no new power cycle
        self.ssh.stop()
        self.seerr.stop()
        req("GET", "/gate?port=5055&signed_in=1", self.signed_in("bob"))
        self.assertTrue(wait_for(lambda: self.phase() == "broken", 8))
        self.assertEqual(self.status()["reason"], "no_boot")
        self.assertEqual(len(self.plug.relay_calls()), 2)

    def test_plug_off_is_left_alone(self):
        self.plug.relay = False
        req("POST", "/jf/wake", SIGNED_JF)
        self.assertTrue(wait_for(lambda: self.phase() == "broken", 8))
        self.assertEqual(self.status()["reason"], "plug_off")
        self.assertEqual(self.plug.relay_calls(), [])
        self.assertEqual(self.am.alerts()[0][1][0]["annotations"]["summary"],
                         "Beefy wake failed: the beefy plug is switched off (left alone on purpose)")

    def test_plug_unreachable(self):
        self.plug.stop()
        req("POST", "/jf/wake", SIGNED_JF)
        self.assertTrue(wait_for(lambda: self.phase() == "broken", 12))
        self.assertEqual(self.status()["reason"], "plug_unreachable")
        a = self.am.alerts()[0][1][0]
        self.assertTrue(a["annotations"]["details"].endswith("plug_power=n/a"), a)

    def test_plug_does_not_switch(self):
        self.plug.switch_works = False
        req("POST", "/jf/wake", SIGNED_JF)
        self.assertTrue(wait_for(lambda: self.phase() == "broken", 15))
        self.assertEqual(self.status()["reason"], "plug_unreachable")
        self.assertEqual(self.plug.relay_calls(), ["/relay?state=0", "/relay?state=1"])
        self.assertTrue(wait_for(lambda: 'beefy_wake_failures_total{reason="plug_unreachable"} 1\n' in metrics(), 2), metrics())

    def test_power_draw_gives_grace(self):
        self.plug.power = 50
        req("POST", "/jf/wake", SIGNED_JF)
        time.sleep(4.5)
        st = self.status()
        self.assertEqual(st["phase"], "waking")
        self.assertTrue(110 <= st["seconds_left"] <= 120, st)
        self.assertEqual(self.plug.relay_calls(), [])

    def test_unsigned_wake_never_touches_plug(self):
        req("GET", "/gate?port=5055")
        time.sleep(3.5)
        self.assertEqual(self.plug.requests, [])
        self.assertTrue(wait_for(lambda: self.phase() == "idle", 4))
        self.assertEqual(self.am.alerts(), [])

    def test_signed_in_status_counts_down(self):
        req("POST", "/jf/wake", SIGNED_JF)
        st = self.status()
        self.assertEqual(st["phase"], "waking")
        self.assertIn(st["seconds_left"], (1, 2))


RUST_ONLY = unittest.skipIf("python" in SUT, "Rust waker only")
STATE = BASE_ENV["WAKE_STATE_FILE"]


@RUST_ONLY
class PowerCycleInterrupted(Base):
    env = REC

    def stop_sut(self, timeout=20):
        self.sut.proc.terminate()
        return self.sut.proc.wait(timeout)

    def test_sigterm_during_plug_off_switches_plug_on(self):
        req("POST", "/jf/wake", SIGNED_JF)
        self.assertTrue(wait_for(lambda: self.plug.relay is False, 6))
        self.assertTrue(os.path.exists(STATE))
        self.assertEqual(self.stop_sut(), 0)
        self.assertTrue(self.plug.relay)
        self.assertEqual(self.plug.relay_calls(), ["/relay?state=0", "/relay?state=1"])
        self.assertFalse(os.path.exists(STATE))
        self.assertTrue(self.log_lines("power cycle interrupted by shutdown, plug switched back on"), self.sut.log())
        a = self.am.alerts()
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0][1][0]["labels"]["alertname"], "BeefyWakeFailed")
        self.assertIn("interrupted", a[0][1][0]["annotations"]["summary"])

    def test_sigterm_when_idle_leaves_plug_alone(self):
        self.assertEqual(self.stop_sut(), 0)
        self.assertEqual(self.plug.requests, [])
        self.assertEqual(self.am.alerts(), [])

    def test_state_file_cleared_after_plug_back_on(self):
        req("POST", "/jf/wake", SIGNED_JF)
        self.assertTrue(wait_for(lambda: self.plug.relay is False, 6))
        self.assertTrue(wait_for(lambda: self.plug.relay is True, 22))
        self.assertTrue(wait_for(lambda: not os.path.exists(STATE), 2))


class InterruptedStateOnStart(Base):
    age = 30
    relay = False

    def before_start(self):
        self.plug.relay = self.relay
        with open(STATE, "w") as f:
            f.write("%.3f\n" % (time.time() - self.age))

    def wait_done(self):
        self.assertTrue(wait_for(lambda: not os.path.exists(STATE), 8), self.sut.log())
        time.sleep(1)


@RUST_ONLY
class ResumeRecentOff(InterruptedStateOnStart):
    def test_plug_switched_on_once(self):
        self.wait_done()
        self.assertTrue(self.plug.relay)
        self.assertEqual(self.plug.relay_calls(), ["/relay?state=1"])
        self.assertTrue(self.log_lines("interrupted power cycle found at start, plug switched back on"), self.sut.log())
        a = self.am.alerts()
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0][1][0]["labels"]["alertname"], "BeefyWakeFailed")
        self.assertIn("interrupted", a[0][1][0]["annotations"]["summary"])
        self.sut.stop()
        self.sut = Sut(self.env)
        self.sut.start()
        self.addCleanup(self.sut.stop)
        time.sleep(1.5)
        self.assertEqual(self.plug.relay_calls(), ["/relay?state=1"])


@RUST_ONLY
class ResumeStale(InterruptedStateOnStart):
    age = 3600

    def test_stale_state_ignored(self):
        self.wait_done()
        self.assertFalse(self.plug.relay)
        self.assertEqual(self.plug.relay_calls(), [])
        self.assertEqual(self.am.alerts(), [])


@RUST_ONLY
class ResumePlugAlreadyOn(InterruptedStateOnStart):
    relay = True

    def test_plug_on_left_alone(self):
        self.wait_done()
        self.assertEqual(self.plug.relay_calls(), [])
        self.assertEqual(self.am.alerts(), [])


# --- background requests (BACKGROUND_SKIP) ---------------------------------------
def tv(device="dev-a", path="/UserItems/Resume?Limit=12&Fields=x", ip="198.51.100.20", client="Moonfin for Android TV"):
    auth = 'MediaBrowser Client="%s", Device="tv"' % client
    if device:
        auth += ', DeviceId="%s"' % device
    return {"Authorization": auth + ', Version="3.0.0", Token="goodtoken123"', "X-Forwarded-Uri": path,
            "X-Forwarded-Method": "GET", "CF-Connecting-IP": ip, "User-Agent": "Mozilla/5.0 (compatible; Moonfin/3.0.0)"}


class BackgroundBase(Base):
    def metric(self, mode):
        with open(BASE_ENV["WAKE_METRICS"]) as f:
            m = re.search(r'^beefy_wake_background_total\{mode="%s"\} (\d+)$' % mode, f.read(), re.M)
        return int(m.group(1)) if m else None

    def wait_idle(self):
        self.assertTrue(wait_for(lambda: self.status()["phase"] == "idle", 8), self.sut.log())

    def last_observe(self, path):
        return [o for o in self.observe() if o["path"] == path][-1]


class BackgroundObserve(BackgroundBase):
    def test_default_mode_is_observe(self):
        self.assertTrue(self.wait_log("background-skip: observe"), self.sut.log())

    def test_lone_resume_still_wakes_and_logs_would_skip(self):
        s, h, b, el = req("GET", JF, tv())
        self.assertEqual((s, h.get("retry-after")), (503, "5"))
        self.assertGreaterEqual(el, 0.8)
        self.assertGreaterEqual(self.wol.count(), 1)
        rec = self.last_observe("/UserItems/Resume")
        self.assertEqual((rec["decision"], rec["would"], rec["class"]), ("wake", "skip-background", "background"))
        self.assertTrue(wait_for(lambda: self.metric("observe") == 1, 2), self.metric("observe"))
        self.assertEqual(self.metric("enforce"), 0)

    def test_device_id_never_logged(self):
        req("GET", JF, tv(device="secret-device-id-42"))
        self.assertNotIn("secret-device-id-42", self.sut.log())

    def test_follow_up_during_campaign_is_classified_not_counted(self):
        req("GET", JF, tv())
        req("GET", JF, tv(path="/Users/u1/Items?Filters=x"))
        rec = self.last_observe("/Users/u1/Items")
        self.assertEqual((rec["decision"], rec["class"]), ("starting", "foreground"))
        self.assertNotIn("would", rec)
        self.assertEqual(self.metric("observe"), 1)


class BackgroundEnforce(BackgroundBase):
    env = {"BACKGROUND_SKIP": "enforce"}

    def test_mode_logged(self):
        self.assertTrue(self.wait_log("background-skip: enforce"), self.sut.log())

    def test_lone_resume_does_not_wake(self):
        s, h, b, el = req("GET", JF, tv())
        self.assertEqual(s, 503)
        self.assertNotIn("retry-after", h)
        self.assertIn(b"Jellyfin is asleep", b)
        self.assertLess(el, 0.8)
        time.sleep(0.3)
        self.assertEqual(self.wol.count(), 0)
        self.assertEqual(self.status()["phase"], "idle")
        rec = self.last_observe("/UserItems/Resume")
        self.assertEqual((rec["decision"], rec["class"], rec["held"]), ("background", "background", 0.0))
        self.assertNotIn("would", rec)
        self.assertTrue(wait_for(lambda: self.metric("enforce") == 1, 2))
        self.assertEqual(self.metric("observe"), 0)

    def test_background_paths(self):
        paths = ["/UserItems/Resume", "/Shows/NextUp?UserId=u", "/Items/Latest", "/Users/u1/Items/Latest?Limit=1",
                 "/Users/u1/Items/Resume", "//useritems/RESUME/"]
        for i, p in enumerate(paths):
            s, _, _, _ = req("GET", JF, tv(device="dev-%d" % i, path=p))
            self.assertEqual(s, 503, p)
        time.sleep(0.3)
        self.assertEqual(self.wol.count(), 0)
        self.assertEqual([o["decision"] for o in self.observe()], ["background"] * len(paths))

    def test_other_paths_still_wake(self):
        for i, p in enumerate(["/Users/u1/Items?Filters=x", "/Users/u1", "/UserViews"]):
            self.wol.reset()
            req("GET", JF, tv(device="fg-%d" % i, path=p))
            self.assertGreaterEqual(self.wol.count(), 1, p)
            self.wait_idle()

    def test_non_get_is_not_background(self):
        req("GET", JF, dict(tv(), **{"X-Forwarded-Method": "POST"}))
        self.assertGreaterEqual(self.wol.count(), 1)

    def test_same_path_repeated_stays_background(self):
        for _ in range(3):
            req("GET", JF, tv())
        time.sleep(0.3)
        self.assertEqual(self.wol.count(), 0)

    def test_app_start_sequence_wakes(self):
        s, _, _, _ = req("GET", "/jf/public-info", tv(path="/System/Info/Public"))
        self.assertEqual(s, 503)
        self.assertGreaterEqual(self.wol.count(), 1)
        req("GET", JF, tv(path="/Users/u1"))
        req("GET", JF, tv())
        self.assertNotIn("background", [o["decision"] for o in self.observe()])

    def test_resume_after_foreground_from_same_device_wakes(self):
        req("GET", "/jf/public-info", tv(path="/System/Info/Public"))
        self.wait_idle()
        self.wol.reset()
        req("GET", JF, tv())
        self.assertGreaterEqual(self.wol.count(), 1)
        self.assertEqual(self.last_observe("/UserItems/Resume")["decision"], "wake")
        self.assertEqual(self.metric("enforce"), 0)

    def test_foreground_through_gate_counts_too(self):
        req("GET", JF, tv(path="/UserViews"))
        self.wait_idle()
        self.wol.reset()
        req("GET", JF, tv())
        self.assertGreaterEqual(self.wol.count(), 1)

    def test_other_device_foreground_does_not_count(self):
        req("GET", JF, tv(device="dev-b", path="/UserViews"))
        self.wait_idle()
        self.wol.reset()
        s, _, _, _ = req("GET", JF, tv(device="dev-a"))
        self.assertEqual(s, 503)
        time.sleep(0.3)
        self.assertEqual(self.wol.count(), 0)

    def test_without_device_id_ip_and_client_are_the_key(self):
        req("GET", JF, tv(device=None, path="/UserViews"))
        self.wait_idle()
        self.wol.reset()
        req("GET", JF, tv(device=None, ip="203.0.113.99"))
        req("GET", JF, tv(device=None, client="Other App"))
        time.sleep(0.3)
        self.assertEqual(self.wol.count(), 0)
        req("GET", JF, tv(device=None))
        self.assertGreaterEqual(self.wol.count(), 1)

    def test_parallel_rows_burst_wakes(self):
        req("GET", JF, tv())
        self.assertEqual(self.wol.count(), 0)
        req("GET", JF, tv(path="/Shows/NextUp"))
        self.assertGreaterEqual(self.wol.count(), 1)
        self.assertEqual(self.last_observe("/Shows/NextUp")["decision"], "wake")

    def test_spaced_background_paths_do_not_wake(self):
        req("GET", JF, tv())
        time.sleep(2.5)
        req("GET", JF, tv(path="/Shows/NextUp"))
        time.sleep(0.3)
        self.assertEqual(self.wol.count(), 0)

    def test_foreground_window_expires(self):
        self.sut.stop()
        self.sut = Sut(dict(self.env, BACKGROUND_FOREGROUND_SECONDS="1"))
        self.sut.start()
        self.addCleanup(self.sut.stop)
        req("GET", JF, tv(path="/UserViews"))
        self.wait_idle()
        self.wol.reset()
        req("GET", JF, tv())
        time.sleep(0.3)
        self.assertEqual(self.wol.count(), 0)

    def test_beefy_up_passes_unclassified(self):
        self.jf.start()
        s, _, b, _ = req("GET", JF, tv())
        self.assertEqual((s, b), (200, b""))
        self.assertEqual(self.observe(), [])

    def test_starting_is_unchanged(self):
        self.ssh.start()
        s, h, _, el = req("GET", JF, tv())
        self.assertEqual((s, h.get("retry-after")), (503, "5"))
        self.assertGreaterEqual(el, 0.8)
        self.assertEqual(self.last_observe("/UserItems/Resume")["decision"], "starting")

    def test_browser_still_gets_signin(self):
        s, _, b, _ = req("GET", JF, dict(BROWSER, **{"X-Forwarded-Uri": "/UserItems/Resume"}))
        self.assertEqual(s, 503)
        rec = self.observe()[0]
        self.assertEqual(rec["decision"], "signin")
        self.assertNotIn("class", rec)


class BackgroundOff(BackgroundBase):
    env = {"BACKGROUND_SKIP": "off"}

    def test_lone_resume_wakes_without_classification(self):
        self.assertTrue(self.wait_log("background-skip: off"))
        req("GET", JF, tv())
        self.assertGreaterEqual(self.wol.count(), 1)
        rec = self.observe()[0]
        self.assertEqual(rec["decision"], "wake")
        self.assertNotIn("would", rec)
        self.assertNotIn("class", rec)
        self.assertEqual((self.metric("observe"), self.metric("enforce")), (0, 0))


class BackgroundInvalid(BackgroundBase):
    env = {"BACKGROUND_SKIP": "Enforce!"}

    def test_invalid_value_falls_back_to_observe(self):
        self.assertTrue(self.wait_log("background-skip: observe (invalid BACKGROUND_SKIP"), self.sut.log())
        req("GET", JF, tv())
        self.assertGreaterEqual(self.wol.count(), 1)


@RUST_ONLY
class LoopSupervisor(Base):
    env = dict(REC, WAKER_TEST_PANIC_RUNS="2")

    def test_panicking_loop_is_restarted_and_alerts_once(self):
        self.assertTrue(wait_for(lambda: len(self.log_lines("recovery loop panicked")) >= 2, 8), self.sut.log())
        self.assertTrue(self.wait_log("recovery loop restarted", 5), self.sut.log())
        req("POST", "/jf/wake", SIGNED_JF)
        self.assertTrue(wait_for(lambda: self.status()["phase"] == "power_cycle", 8), self.sut.log())
        a = [x for x in self.am.alerts() if "loop" in x[1][0]["annotations"]["summary"]]
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0][1][0]["labels"]["alertname"], "BeefyWakeFailed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
