"""Black-box tests: the service runs as a subprocess against fake gluetun, qBittorrent and Docker APIs on 127.0.0.1.

Env: SUT_CMD (command line of the service), HAPROXY_CFG (socket-proxy allow-list), LEGACY_WEB (legacy web-server.py, source of the page), HISTORY_FIXTURE (optional real port-history.json).
"""
import ast
import base64
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
import unittest
import urllib.error
import urllib.request

from mocks import World, load_allow_list

SUT_CMD = shlex.split(os.environ.get("SUT_CMD", "/usr/local/bin/entrypoint.sh"))
HAPROXY_CFG = os.environ.get("HAPROXY_CFG", "/haproxy.cfg")
LEGACY_WEB = os.environ.get("LEGACY_WEB", "/src/legacy/web-server.py")
DATA = "/tmp/data"
SECRETS = "/tmp/secrets"
WEB = "http://127.0.0.1:8088"
TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4}$")
KEYS = ["timestamp", "event", "port", "old_port", "vpn_ip", "message"]


def legacy_html():
    tree = ast.parse(open(LEGACY_WEB).read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "HTML":
            return node.value.value
    raise RuntimeError("HTML not found in legacy web-server.py")


def http(method, path, user=None, pw=None, auth_header=None):
    req = urllib.request.Request(WEB + path, method=method)
    if user is not None:
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode())
    if auth_header:
        req.add_header("Authorization", auth_header)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


class Base(unittest.TestCase):
    web_user, web_pass = "webuser", "web pass"
    env_extra = {}

    def setUp(self):
        shutil.rmtree(DATA, ignore_errors=True)
        shutil.rmtree(SECRETS, ignore_errors=True)
        os.makedirs(DATA)
        os.makedirs(SECRETS)
        self.world = World(load_allow_list(HAPROXY_CFG))
        self.configure(self.world)
        self.world.start({"qbit": 8080, "gluetun": 8000, "docker": 2375})
        for name, val in {"qbit_pass": self.world.qbit_pass, "gluetun_pass": self.world.gluetun_pass, "web_pass": self.web_pass}.items():
            with open(f"{SECRETS}/{name}", "w") as f:
                f.write(val + "\n")
        self.seed()
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp",
            "DOCKER_HOST": "tcp://127.0.0.1:2375", "GLUETUN_IP": "127.0.0.1",
            "QBIT_USER": self.world.qbit_user, "QBIT_PASS_FILE": f"{SECRETS}/qbit_pass",
            "GLUETUN_AUTH_USER": self.world.gluetun_user, "GLUETUN_AUTH_PASS_FILE": f"{SECRETS}/gluetun_pass",
            "WEB_PORT": "8088", "WEB_USER": self.web_user, "WEB_PASS_FILE": f"{SECRETS}/web_pass",
            "CHECK_INTERVAL": "4", "SESSION_CHECK_INTERVAL": "1", "ZERO_RETRY_INTERVAL": "1", "ZERO_PORT_LIMIT": "3",
            "TZ": "Europe/Zurich",
        }
        env.update(self.env_extra)
        self.lines = []
        self.proc = subprocess.Popen(SUT_CMD, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True, text=True)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.append(line.rstrip("\n"))

    def tearDown(self):
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.proc.wait()
        self.world.stop()
        if self._outcome.result.errors or self._outcome.result.failures:
            print("\n--- SUT output ---\n" + "\n".join(self.lines[-60:]))

    def configure(self, world):
        pass

    def seed(self):
        pass

    def wait_log(self, pattern, timeout=60, after=0):
        rx = re.compile(pattern)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for i, line in enumerate(self.lines[after:], after):
                if rx.search(line):
                    return i + 1
            if self.proc.poll() is not None:
                self.fail(f"service exited ({self.proc.returncode}) before {pattern!r}")
            time.sleep(0.1)
        self.fail(f"timeout waiting for {pattern!r}")

    def wait_web(self, timeout=20):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                http("GET", "/nope")
                return
            except OSError:
                time.sleep(0.1)
        self.fail("web server did not come up")

    def history(self):
        try:
            with open(f"{DATA}/port-history.json") as f:
                return [json.loads(line) for line in f if line.strip()]
        except FileNotFoundError:
            return []

    def raw_history(self):
        with open(f"{DATA}/port-history.json") as f:
            return [line for line in f if line.strip()]


class SyncFlow(Base):
    def test_sync_flow(self):
        w = self.world
        n = self.wait_log(r"^Port updated to 45000$", 60)
        self.assertEqual(w.qbit_calls("/api/v2/app/setPreferences")[0], {"current_network_interface": "tun0"})
        self.assertEqual(w.docker_actions()[0], ("restart", "qbittorrent_mouse"))
        self.assertEqual(w.prefs["listen_port"], 45000)
        self.assertIn({"hashes": "all"}, w.qbit_calls("/api/v2/torrents/reannounce"))
        self.assertIn({"username": "admin", "password": "p@ss w&rd=1"}, w.logins)
        self.assertEqual(w.gluetun_bad_auth, 0)
        self.wait_log(r"^Reannounce triggered\.$", 10, n)
        n = self.wait_log(r"^Port OK: VPN=45000, qBit=45000$", 30, n)

        h = self.history()
        self.assertEqual(h[0]["event"], "startup")
        self.assertEqual((h[0]["port"], h[0]["old_port"], h[0]["vpn_ip"], h[0]["message"]), (0, 0, "", "Port updater started"))
        up = [e for e in h if e["event"] == "port_update"]
        self.assertEqual(len(up), 1)
        self.assertEqual((up[0]["port"], up[0]["old_port"], up[0]["vpn_ip"]), (45000, 0, "198.51.100.7"))
        self.assertEqual(up[0]["message"], "ProtonVPN assigned new port 45000 (was 0)")
        for line in self.raw_history():
            self.assertEqual(list(json.loads(line)), KEYS)
            self.assertRegex(json.loads(line)["timestamp"], TS_RE)
        self.assertIn('"port":45000,"old_port":0,', self.raw_history()[1])

        with w.lock:
            w.ports = [46000]
        n = self.wait_log(r"ProtonVPN assigned a new forwarded port: 46000 \(was: 45000\)", 20, n)
        self.wait_log(r"^Port update needed: VPN=46000, qBit=45000 \(last=45000\)$", 5, n - 1)
        n = self.wait_log(r"^Port updated to 46000$", 10, n)
        self.assertEqual(w.prefs["listen_port"], 46000)
        up = [e for e in self.history() if e["event"] == "port_update"]
        self.assertEqual((up[-1]["port"], up[-1]["old_port"]), (46000, 45000))

        with w.lock:
            w.qbit_restart()
        t0 = time.monotonic()
        n = self.wait_log(r"^qBittorrent session expired \(restart\?\) - re-applying port now$", 10, n)
        n = self.wait_log(r"^Port update needed: VPN=46000, qBit=1 \(last=46000\)$", 10, n)
        self.wait_log(r"^Port updated to 46000$", 10, n)
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(w.prefs["listen_port"], 46000)

        with w.lock:
            w.qbit_available = False
        n = self.wait_log(r"^Attempting to reattach qBittorrent/mousehole/sabnzbd to gluetun network\.\.\.$", 30, n)
        self.wait_log(r"^Port updated to 46000$", 40, n)
        acts = w.docker_actions()
        for c in ("qbittorrent_mouse", "mousehole", "sabnzbd"):
            self.assertIn(("restart", c), acts)
        self.assertNotIn(("restart", "gluetun_mouse"), acts)
        self.assertEqual(w.docker_denied, [])
        self.assertEqual(w.gluetun_bad_auth, 0)


class ZeroPort(Base):
    def configure(self, w):
        w.ports = [0]
        w.port_after_restart = 47000
        w.health = ["starting", "healthy"]

    def test_zero_port_restarts_stack(self):
        w = self.world
        n = self.wait_log(r"^Port is 0 \(1/3\): VPN=0, qBit=1$", 60)
        n = self.wait_log(r"^Port is 0 — will retry in 1 seconds \(faster retry\)\.\.\.$", 5, n)
        self.wait_log(r"^Port is 0 \(3/3\): VPN=0, qBit=1$", 20, n)
        n = self.wait_log(r"^Port has been 0 for 0 minutes — restarting stack\.\.\.$", 5, n)
        n = self.wait_log(r"^Gluetun is healthy\.$", 30, n)
        n = self.wait_log(r"^Stack restarted\. Checking for new port immediately\.\.\.$", 60, n)
        self.wait_log(r"^Port updated to 47000$", 30, n)

        acts = [a for a in w.docker_actions() if a[0] != "inspect"]
        self.assertEqual(acts[0], ("restart", "qbittorrent_mouse"))
        rest = acts[1:]
        stops = [a for a in rest[:3]]
        self.assertEqual(sorted(stops), sorted([("stop", "qbittorrent_mouse"), ("stop", "mousehole"), ("stop", "sabnzbd")]))
        self.assertEqual(rest[3], ("restart", "gluetun_mouse"))
        self.assertEqual(rest[4:7], [("start", "qbittorrent_mouse"), ("start", "mousehole"), ("start", "sabnzbd")])
        self.assertEqual(rest[7], ("restart", "qbittorrent_mouse"))
        self.assertGreaterEqual(len([a for a in w.docker_actions() if a == ("inspect", "gluetun_mouse")]), 2)
        self.assertEqual(w.docker_denied, [])

        h = self.history()
        zero = [e for e in h if e["event"] == "zero_port"]
        self.assertEqual([e["message"] for e in zero], ["Port is 0 (1/3)", "Port is 0 (2/3)", "Port is 0 (3/3)"])
        self.assertTrue(all(e["port"] == 0 and e["old_port"] == 0 and e["vpn_ip"] == "198.51.100.7" for e in zero))
        sr = [e for e in h if e["event"] == "stack_restart"]
        self.assertEqual(len(sr), 1)
        self.assertEqual(sr[0]["message"], "Port remained 0 for 3 cycles — restarting stack")
        up = [e for e in h if e["event"] == "port_update"]
        self.assertEqual((up[0]["port"], up[0]["old_port"]), (47000, 0))
        self.assertEqual([e["event"] for e in h], ["startup", "zero_port", "zero_port", "zero_port", "stack_restart", "port_update"])


SEED = [
    '{"timestamp":"2026-11-01T10:00:00+0100","event":"startup","port":0,"old_port":0,"vpn_ip":"","message":"Port updater started"}',
    '{"timestamp":"2026-11-01T10:01:00+0100","event":"port_update","port":40000,"old_port":0,"vpn_ip":"203.0.113.9","message":"ProtonVPN assigned new port 40000 (was 0)"}',
    'not json at all',
    '',
    '{"timestamp":"2026-11-01T11:00:00+0100","event":"zero_port","port":0,"old_port":40000,"vpn_ip":"","message":"Port is 0 (1/3) — x"}',
]


class Web(Base):
    def configure(self, w):
        w.qbit_available = False

    def seed(self):
        fixture = os.environ.get("HISTORY_FIXTURE")
        if fixture:
            shutil.copy(fixture, f"{DATA}/port-history.json")
        else:
            with open(f"{DATA}/port-history.json", "w") as f:
                f.write("\n".join(SEED) + "\n")
        with open(f"{DATA}/port-history.json") as f:
            self.expected = []
            for line in f:
                line = line.strip()
                if line:
                    try:
                        self.expected.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    def test_web(self):
        self.wait_web()
        u, p = self.web_user, self.web_pass
        code, hdr, _ = http("GET", "/")
        self.assertEqual(code, 401)
        self.assertEqual(hdr.get("WWW-Authenticate"), 'Basic realm="port-updater"')
        self.assertEqual(http("GET", "/", u, "wrong")[0], 401)
        self.assertEqual(http("GET", "/api/history", "x", p)[0], 401)
        self.assertEqual(http("GET", "/api/history", auth_header="Bearer abc")[0], 401)

        html = legacy_html().encode()
        for path in ("/", "/index.html"):
            code, hdr, body = http("GET", path, u, p)
            self.assertEqual(code, 200)
            self.assertEqual(hdr["Content-Type"], "text/html; charset=utf-8")
            self.assertEqual(body, html)

        code, hdr, body = http("GET", "/api/history", u, p)
        self.assertEqual(code, 200)
        self.assertEqual(hdr["Content-Type"], "application/json")
        self.assertEqual(int(hdr["Content-Length"]), len(body))
        hist = json.loads(body)
        self.assertEqual(hist[: len(self.expected)], self.expected)

        code, hdr, body = http("GET", "/api/status", u, p)
        self.assertEqual(code, 200)
        self.assertEqual(hdr["Content-Type"], "application/json")
        st = json.loads(body)
        self.assertEqual(sorted(st), ["real_ip", "vpn_ip"])
        self.assertIsInstance(st["real_ip"], str)
        if not os.environ.get("HISTORY_FIXTURE"):
            self.assertEqual(st["vpn_ip"], "203.0.113.9")
            self.assertEqual(st["real_ip"], "unknown")

        self.assertEqual(http("GET", "/nope", u, p)[0], 404)
        self.assertEqual(http("GET", "/api/history?x=1", u, p)[0], 404)
        self.assertEqual(http("GET", "/nope")[0], 401)
        self.assertEqual(http("POST", "/api/history", u, p)[0], 501)
        self.assertEqual(http("POST", "/")[0], 501)


class WebNoAuth(Base):
    web_pass = ""
    env_extra = {"WEB_USER": ""}

    def configure(self, w):
        w.qbit_available = False

    def test_open_without_credentials(self):
        self.wait_web()
        end = time.monotonic() + 10
        while True:
            code, _, body = http("GET", "/api/history")
            if json.loads(body) or time.monotonic() > end:
                break
            time.sleep(0.2)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), [{"timestamp": json.loads(body)[0]["timestamp"], "event": "startup", "port": 0, "old_port": 0, "vpn_ip": "", "message": "Port updater started"}])
        code, _, body = http("GET", "/api/status")
        self.assertEqual(json.loads(body)["vpn_ip"], None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
