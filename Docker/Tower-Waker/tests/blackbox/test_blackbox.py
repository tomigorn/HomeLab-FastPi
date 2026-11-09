#!/usr/bin/env python3
"""Black-box tests for Tower-Waker: real HTTP against the running program, fakes for tower and the WoL broadcast.

Runs inside a network-less container (run.sh), everything on loopback:
  127.0.0.1:9002  the waker (SUT)
  127.0.0.2       tower (sshd on 22, Nextcloud on 8080)
  127.0.0.3:9     WoL sink (TARGET_BROADCAST)
SUT is the command line: "python /app/waker.py" (old) or "/sut/tower-waker" (new).
"""
import http.client
import json
import os
import shlex
import socket
import subprocess
import threading
import time
import unittest

SUT = os.environ.get("SUT", "python /app/waker.py")
with open(os.environ.get("VERSION_FILE", "/app/VERSION")) as _f:
    VERSION = _f.read().strip()
MAC = "02:00:5e:40:50:60"
MAGIC = b"\xff" * 6 + bytes.fromhex(MAC.replace(":", "")) * 16
TOWER = "127.0.0.2"
PORT = 9002

BASE_ENV = {
    "WAKER_LISTEN_PORT": str(PORT), "WAKER_BIND": "127.0.0.1", "TARGET_MAC": MAC,
    "TARGET_BROADCAST": "127.0.0.3", "TARGET_PROBE_HOST": TOWER, "TARGET_PROBE_PORT": "8080",
    "WAKE_COUNTDOWN": "120", "TARGET_SSH_USER": "root", "TARGET_HISTORY_SINCE": "0",
    "WAKE_RETRY_INTERVAL": "1", "WAKE_RETRY_WINDOW": "3",
    "PATH": "/usr/local/bin:/usr/bin:/bin", "TZ": "UTC",
}


def wait_for(cond, timeout, step=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


class TcpPort:
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


class Sut:
    def __init__(self, env):
        self.env = dict(BASE_ENV, **env)
        self.lines = []
        self.lock = threading.Lock()
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen(shlex.split(SUT), env=self.env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, errors="replace")
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


def req(method, path, headers=None, timeout=30, body=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    t = time.monotonic()
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, data, time.monotonic() - t


FAKES = {}


def setUpModule():
    FAKES["wol"] = WolSink()
    FAKES["ssh"] = TcpPort(TOWER, 22)
    FAKES["nc"] = TcpPort(TOWER, 8080)
    FAKES["other"] = TcpPort(TOWER, 445)


class Base(unittest.TestCase):
    env = {}

    def setUp(self):
        self.wol, self.ssh, self.nc, self.other = FAKES["wol"], FAKES["ssh"], FAKES["nc"], FAKES["other"]
        for p in (self.ssh, self.nc, self.other):
            p.stop()
        self.wol.reset()
        self.sut = Sut(self.env)
        self.sut.start()
        self.addCleanup(self.sut.stop)

    def log_lines(self, needle):
        return [line for line in self.sut.log().splitlines() if needle in line]

    def wait_log(self, needle, timeout=2):
        wait_for(lambda: self.log_lines(needle), timeout)
        return self.log_lines(needle)


WAKING_PAGE = b"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="5">
<title>Waking tower...</title>
<style>
  html,body{height:100%;margin:0}
  body{display:flex;align-items:center;justify-content:center;
       font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3}
  .card{text-align:center;max-width:28rem;padding:2rem}
  .spin{width:3rem;height:3rem;margin:0 auto 1.5rem;border:4px solid #30363d;
        border-top-color:#58a6ff;border-radius:50%;animation:s 1s linear infinite}
  @keyframes s{to{transform:rotate(360deg)}}
  h1{font-size:1.3rem;margin:.5rem 0}
  p{color:#8b949e;margin:.25rem 0}
</style></head>
<body><div class="card">
  <div class="spin"></div>
  <h1>Waking up tower...</h1>
  <p>A magic packet is on its way. This page refreshes automatically.</p>
  <p>The server should be ready in under a minute.</p>
</div></body></html>"""


class Pages(Base):
    def test_root_page(self):
        s, h, b, _ = req("GET", "/")
        self.assertEqual((s, h["content-type"]), (200, "text/html; charset=utf-8"))
        self.assertEqual(int(h["content-length"]), len(b))
        t = b.decode()
        self.assertIn("<title>Wake tower</title>", t)
        self.assertIn("const AUTOWAKE = false;", t)
        self.assertIn("const TOTAL = 120;", t)
        self.assertIn('<div class="count" id="count">~120s</div>', t)
        self.assertIn('<div class="ver">v%s</div>' % VERSION, t)
        self.assertIn("<summary>tower history</summary>", t)
        for ph in ("__COUNTDOWN__", "__AUTOWAKE__", "__VERSION__"):
            self.assertNotIn(ph, t)
        self.assertEqual(self.wol.count(), 0)

    def test_wol_page(self):
        s, _, b, _ = req("GET", "/wol/")
        self.assertEqual(s, 200)
        self.assertIn(b"const AUTOWAKE = true;", b)
        time.sleep(0.3)
        self.assertEqual(self.wol.count(), 0)

    def test_nc_page(self):
        for p in ("/nc", "/nc/", "/nc?x=1"):
            s, h, b, _ = req("GET", p)
            self.assertEqual((s, h["content-type"]), (200, "text/html; charset=utf-8"), p)
            t = b.decode()
            self.assertIn('<div class="n" id="n">120</div>', t)
            self.assertIn("let left = 120, waited = 0;", t)
            self.assertIn("if (waited > 63) {", t)
            self.assertIn("<footer>tower-waker %s</footer>" % VERSION, t)
            self.assertIn('const base = "/tower-wake/";', t)
            self.assertIn('textContent = left > 0 ? left : "\u2026";', t)
        self.assertEqual(self.wol.count(), 0)

    def test_unknown_404_and_methods_501(self):
        for p in ("/x", "/nc/x", "/jf", "/stream-auth", "/tower-wake/"):
            self.assertEqual(req("GET", p)[0], 404, p)
        for m in ("HEAD", "PUT", "DELETE", "OPTIONS"):
            self.assertEqual(req(m, "/")[0], 501, m)

    def test_history_inert(self):
        s, h, b, _ = req("GET", "/history")
        self.assertEqual((s, h["content-type"], b), (503, "application/json", b'{"error": "history key not installed"}'))

    def test_access_log_line(self):
        req("GET", "/status?q=1")
        self.assertTrue(self.wait_log('127.0.0.1 - "GET /status?q=1 HTTP/1.1" 200 -'), self.sut.log())

    def test_banner(self):
        self.assertTrue(self.wait_log("tower-waker listening on 127.0.0.1:9002 - page=/ gate=/gate, wake %s via 127.0.0.3, probe 127.0.0.2:8080" % MAC))

    def test_parallel(self):
        out = []
        ts = [threading.Thread(target=lambda: out.append(req("GET", "/")[0])) for _ in range(40)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(out, [200] * 40)

    def test_slow_client_does_not_block(self):
        s = socket.create_connection(("127.0.0.1", PORT))
        s.sendall(b"GET / HTTP/1.1\r\n")
        self.assertEqual(req("GET", "/status", timeout=2)[0], 200)
        s.close()


class Status(Base):
    def test_status_and_nc_status(self):
        for p in ("/status", "/nc/status"):
            s, h, b, _ = req("GET", p)
            self.assertEqual((s, h["content-type"], b), (200, "application/json", b'{"up": false}'), p)
        self.ssh.start()
        self.assertEqual(req("GET", "/status")[2], b'{"up": false}')
        self.nc.start()
        for p in ("/status", "/nc/status"):
            self.assertEqual(req("GET", p)[2], b'{"up": true}', p)


class Wake(Base):
    def test_get_405(self):
        for p in ("/wake", "/nc/wake"):
            s, h, b, _ = req("GET", p, {"X-Wake": "1"})
            self.assertEqual((s, h["content-type"], b), (405, "application/json", b'{"error": "POST only"}'), p)
        self.assertEqual(self.wol.count(), 0)

    def test_csrf(self):
        for p in ("/wake", "/nc/wake"):
            for hd in ({}, {"X-Wake": "true"}, {"X-Wake": "1", "Origin": "https://evil.example.com"}, {"X-Wake": "1", "Origin": ""}):
                s, _, b, _ = req("POST", p, hd)
                self.assertEqual((s, b), (403, b'{"error": "needs X-Wake: 1 from this origin"}'), (p, hd))
        self.assertEqual(self.wol.count(), 0)

    def test_manual_wake(self):
        s, h, b, _ = req("POST", "/wake", {"X-Wake": "1", "Origin": "https://tower-wol.example.com", "Host": "tower-wol.example.com"})
        self.assertEqual((s, h["content-type"], b), (200, "application/json", b'{"sent": true}'))
        self.assertTrue(wait_for(lambda: self.wol.count() >= 1, 2))
        self.assertEqual(self.wol.packets[0][1], MAGIC)
        self.assertTrue(self.wait_log("manual wake -> sent WoL to %s via 127.0.0.3" % MAC))

    def test_nc_wake_logs_user(self):
        s, _, b, _ = req("POST", "/nc/wake", {"X-Wake": "1", "X-Authentik-Username": "carol"})
        self.assertEqual((s, b), (200, b'{"sent": true}'))
        self.assertTrue(self.wait_log("nc wake by carol -> sent WoL to %s via 127.0.0.3" % MAC))
        req("POST", "/nc/wake", {"X-Wake": "1"})
        self.assertTrue(self.wait_log("nc wake by ? -> sent WoL"))
        req("POST", "/nc/wake", {"X-Wake": "1", "X-Authentik-Username": "x" * 80})
        self.assertTrue(self.wait_log("nc wake by %s -> " % ("x" * 64)))

    def test_campaign_resends_until_window_ends(self):
        req("POST", "/wake", {"X-Wake": "1"})
        self.assertTrue(wait_for(lambda: self.wol.count() >= 3, 3.5), self.wol.count())
        time.sleep(1.5)
        n = self.wol.count()
        self.assertLessEqual(n, 4)
        time.sleep(1.5)
        self.assertEqual(self.wol.count(), n)

    def test_campaign_stops_when_up(self):
        req("POST", "/wake", {"X-Wake": "1"})
        self.nc.start()
        time.sleep(2.5)
        self.assertEqual(self.wol.count(), 1)

    def test_single_flight(self):
        for _ in range(5):
            req("POST", "/wake", {"X-Wake": "1"})
        self.assertTrue(wait_for(lambda: self.wol.count() >= 5, 1))
        time.sleep(1.4)
        self.assertEqual(self.wol.count(), 6)

    def test_campaign_probes_probe_port_not_ssh(self):
        req("POST", "/wake", {"X-Wake": "1"})
        self.ssh.start()
        self.assertTrue(wait_for(lambda: self.wol.count() >= 2, 2.5))


class WolFailure(Base):
    env = {"TARGET_BROADCAST": "256.1.1.1"}

    def test_failed_send(self):
        s, _, b, _ = req("POST", "/wake", {"X-Wake": "1"})
        self.assertEqual((s, b), (200, b'{"sent": false}'))
        self.assertTrue(self.wait_log("WoL send failed: "))
        s, _, b, _ = req("GET", "/gate")
        self.assertEqual((s, b), (503, WAKING_PAGE))


class Gate(Base):
    def test_up_passes(self):
        self.nc.start()
        s, h, b, _ = req("GET", "/gate")
        self.assertEqual((s, h["content-type"], b), (200, "text/plain", b""))
        self.assertEqual(self.wol.count(), 0)

    def test_down_wakes(self):
        s, h, b, _ = req("GET", "/gate?port=8080")
        self.assertEqual((s, h["content-type"], h.get("retry-after"), b), (503, "text/html; charset=utf-8", "5", WAKING_PAGE))
        self.assertTrue(wait_for(lambda: self.wol.count() >= 1, 2))
        self.assertTrue(self.wait_log("tower down (127.0.0.2:8080) - sent WoL to %s via 127.0.0.3" % MAC))

    def test_port_override_and_fallback(self):
        self.other.start()
        self.assertEqual(req("GET", "/gate?port=445")[0], 200)
        self.nc.start()
        for q in ("port=x", "port=0", "port=65536", "port="):
            self.assertEqual(req("GET", "/gate?" + q)[0], 200, q)
        self.assertEqual(self.wol.count(), 0)


NC = "/gate?port=8080&policy=nextcloud"


class NextcloudGate(Base):
    def test_up_passes(self):
        self.nc.start()
        s, _, b, _ = req("GET", NC, {"Accept": "text/html"})
        self.assertEqual((s, b), (200, b""))

    def test_scanner_refused_no_wake(self):
        s, h, b, _ = req("GET", NC, {"User-Agent": "zgrab/0.x", "X-Forwarded-Uri": "/.env?x=1", "X-Forwarded-For": "203.0.113.9"})
        self.assertEqual((s, h["content-type"], b), (503, "text/plain; charset=utf-8", b"Nextcloud is asleep.\n"))
        self.assertNotIn("retry-after", h)
        time.sleep(0.3)
        self.assertEqual(self.wol.count(), 0)
        self.assertTrue(self.wait_log("nextcloud refuse (no wake) 203.0.113.9 /.env zgrab/0.x"))

    def test_browser_gets_signin_no_wake(self):
        s, h, b, _ = req("GET", NC, {"Accept": "text/html", "CF-Connecting-IP": "198.51.100.1", "X-Forwarded-For": "10.0.0.1"})
        self.assertEqual((s, h["content-type"]), (503, "text/html; charset=utf-8"))
        self.assertNotIn("retry-after", h)
        t = b.decode()
        self.assertIn("<title>Nextcloud is asleep</title>", t)
        self.assertIn('<a class="btn" href="/tower-wake/">Sign in to start it</a>', t)
        self.assertIn("<p>It takes about two minutes to start after you sign in.</p>", t)
        self.assertEqual(self.wol.count(), 0)
        self.assertTrue(self.wait_log("nextcloud signin (no wake) 198.51.100.1 / -"))

    def test_clients_wake(self):
        cases = [{"Authorization": "Basic dXNlcjpwYXNz"}, {"User-Agent": "Mozilla/5.0 (Windows) mirall/3.14"},
                 {"User-Agent": "Mozilla/5.0 (Android) Nextcloud-android/30"}, {"Cookie": "a=b; nc_session_id=1"},
                 {"Cookie": "oc_sessionPassphrase=x"}, {"Cookie": "NC_USERNAME=x", "Accept": "text/html"}]
        for hd in cases:
            self.wol.reset()
            s, h, b, _ = req("GET", NC, hd)
            self.assertEqual((s, h.get("retry-after"), b), (503, "5", WAKING_PAGE), hd)
            self.assertTrue(wait_for(lambda: self.wol.count() >= 1, 2), hd)
            self.sut.stop()
            self.sut = Sut({})
            self.sut.start()
        self.addCleanup(self.sut.stop)

    def test_wake_log_line(self):
        req("GET", NC, {"User-Agent": "mirall/" + "9" * 100, "X-Forwarded-For": "203.0.113.4"})
        self.assertTrue(self.wait_log("tower down (127.0.0.2:8080) - sent WoL to %s via 127.0.0.3 [nextcloud client 203.0.113.4 %s]" % (MAC, ("mirall/" + "9" * 100)[:60])))

    def test_starting_when_ssh_answers(self):
        self.ssh.start()
        s, h, b, _ = req("GET", NC, {"Accept": "text/html", "X-Forwarded-Uri": "/apps/files/?dir=/"})
        self.assertEqual((s, h.get("retry-after"), b), (503, "5", WAKING_PAGE))
        self.assertEqual(self.wol.count(), 0)
        self.assertTrue(self.wait_log("nextcloud starting (no wake) ? /apps/files/ -"))

    def test_starting_during_campaign(self):
        req("POST", "/wake", {"X-Wake": "1"})
        n = self.wol.count()
        s, _, b, _ = req("GET", NC, {"Cookie": "nc_token=1"})
        self.assertEqual((s, b), (503, WAKING_PAGE))
        self.assertTrue(self.wait_log("nextcloud starting (no wake)"))

    def test_log_fields_truncated(self):
        req("GET", NC, {"User-Agent": "u" * 100, "X-Forwarded-Uri": "/" + "p" * 200, "CF-Connecting-IP": "c" * 60})
        self.assertTrue(self.wait_log("nextcloud refuse (no wake) %s /%s %s" % ("c" * 45, "p" * 119, "u" * 60)))


class Startup(unittest.TestCase):
    def run_bad(self, env):
        e = {k: v for k, v in dict(BASE_ENV, **env).items() if v is not None}
        p = subprocess.run(shlex.split(SUT), env=e, capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout + p.stderr

    def test_missing(self):
        rc, out = self.run_bad({"TARGET_MAC": None, "TARGET_PROBE_HOST": ""})
        self.assertNotEqual(rc, 0)
        self.assertIn("missing required env: TARGET_MAC, TARGET_PROBE_HOST", out)

    def test_bad_mac(self):
        rc, _ = self.run_bad({"TARGET_MAC": "zz:00:5e:40:50:60"})
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
