"""Fakes for gluetun's control server, qBittorrent's WebUI API and the Docker API behind socket-proxy-portupdater."""
import base64
import json
import re
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def load_allow_list(cfg_path):
    """(method, regex) pairs from the haproxy allow-list the real proxy uses."""
    rules = []
    pat = re.compile(r"http-request allow if METH_(\w+) \{ path -m reg (\S+) \}")
    with open(cfg_path) as f:
        for line in f:
            m = pat.search(line)
            if m:
                rules.append((m.group(1), re.compile(m.group(2))))
    if not rules:
        raise RuntimeError(f"no allow rules in {cfg_path}")
    return rules


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _send(self, code, body=b"", ctype="text/plain", headers=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if code not in (204, 304):
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD" and code not in (204, 304):
            self.wfile.write(body)

    def do_GET(self):
        self.server.world.handle(self.server.kind, self, "GET", self._body())

    def do_POST(self):
        self.server.world.handle(self.server.kind, self, "POST", self._body())

    def do_HEAD(self):
        self.server.world.handle(self.server.kind, self, "HEAD", b"")


class World:
    """All three fakes share one lock and one event log, so tests can assert on order."""

    def __init__(self, allow_list, gluetun_user="gtuser", gluetun_pass="gt pass:1", qbit_user="admin", qbit_pass="p@ss w&rd=1"):
        self.lock = threading.Lock()
        self.allow = allow_list
        self.events = []
        self.gluetun_user, self.gluetun_pass = gluetun_user, gluetun_pass
        self.qbit_user, self.qbit_pass = qbit_user, qbit_pass
        self.ports = [45000]
        self.port_after_restart = None
        self.vpn_ip = "198.51.100.7"
        self.gluetun_bad_auth = 0
        self.health = ["healthy"]
        self.qbit_available = True
        self.sid = None
        self.prefs = {"listen_port": 1, "current_network_interface": ""}
        self.reset_port_on_restart = True
        self.logins = []
        self.docker_denied = []
        self.servers = []

    def log(self, *ev):
        self.events.append((time.monotonic(),) + ev)

    def docker_actions(self):
        with self.lock:
            return [(e[2], e[3]) for e in self.events if e[1] == "docker"]

    def qbit_calls(self, path):
        with self.lock:
            return [e[3] for e in self.events if e[1] == "qbit" and e[2] == path]

    def start(self, ports):
        for kind, port in ports.items():
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            srv.daemon_threads = True
            srv.kind, srv.world = kind, self
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.servers.append(srv)

    def stop(self):
        for s in self.servers:
            s.shutdown()
            s.server_close()

    def qbit_restart(self):
        self.sid = None
        if self.reset_port_on_restart:
            self.prefs["listen_port"] = 1

    def handle(self, kind, h, method, body):
        with self.lock:
            getattr(self, "_" + kind)(h, method, body)

    def _gluetun(self, h, method, body):
        want = "Basic " + base64.b64encode(f"{self.gluetun_user}:{self.gluetun_pass}".encode()).decode()
        if h.headers.get("Authorization") != want:
            self.gluetun_bad_auth += 1
            return h._send(401, "Unauthorized\n")
        if method == "GET" and h.path == "/v1/portforward":
            port = self.ports.pop(0) if len(self.ports) > 1 else self.ports[0]
            self.log("gluetun", "portforward", port)
            return h._send(200, json.dumps({"port": port}) + "\n", "application/json")
        if method == "GET" and h.path == "/v1/publicip/ip":
            return h._send(200, json.dumps({"public_ip": self.vpn_ip, "country": "Switzerland"}) + "\n", "application/json")
        h._send(404, "404 page not found\n")

    def _qbit(self, h, method, body):
        path = urllib.parse.urlsplit(h.path).path
        if not self.qbit_available:
            return h._send(503, "unavailable")
        cookie = h.headers.get("Cookie") or ""
        authed = self.sid is not None and f"SID={self.sid}" in [c.strip() for c in cookie.split(";")]
        form = {k: v[0] for k, v in urllib.parse.parse_qs(body.decode(), keep_blank_values=True).items()}
        if method == "GET" and path == "/":
            return h._send(200, "<html>qBittorrent</html>", "text/html")
        if method == "POST" and path == "/api/v2/auth/login":
            self.logins.append(form)
            self.log("qbit", path, form)
            if form.get("username") == self.qbit_user and form.get("password") == self.qbit_pass:
                self.sid = secrets.token_hex(8)
                return h._send(200, "Ok.", headers={"Set-Cookie": f"SID={self.sid}; HttpOnly; SameSite=Strict; path=/"})
            return h._send(200, "Fails.")
        if not authed:
            return h._send(403, "Forbidden")
        if method == "GET" and path == "/api/v2/app/version":
            return h._send(200, "v5.2.4")
        if method == "GET" and path == "/api/v2/app/preferences":
            return h._send(200, json.dumps(self.prefs), "application/json")
        if method == "POST" and path == "/api/v2/app/setPreferences":
            new = json.loads(form["json"])
            self.prefs.update(new)
            self.log("qbit", path, new)
            return h._send(200, "")
        if method == "POST" and path == "/api/v2/torrents/reannounce":
            self.log("qbit", path, form)
            return h._send(200, "")
        h._send(404, "Not Found")

    def _docker(self, h, method, body):
        path = urllib.parse.urlsplit(h.path).path
        if not any(m == method and rx.search(path) for m, rx in self.allow):
            self.docker_denied.append((method, h.path))
            return h._send(403, "<html><body><h1>403 Forbidden</h1>\nRequest forbidden by administrative rules.\n</body></html>\n", "text/html")
        ping_headers = {"Api-Version": "1.52", "Docker-Experimental": "false", "Ostype": "linux"}
        if re.search(r"/_ping$", path):
            return h._send(200, "OK", headers=ping_headers)
        m = re.search(r"/containers/([^/]+)/(json|start|stop|restart)$", path)
        name, action = m.group(1), m.group(2)
        if action == "json":
            status = self.health.pop(0) if len(self.health) > 1 else self.health[0]
            self.log("docker", "inspect", name)
            doc = {"Id": "0" * 64, "Name": "/" + name, "State": {"Status": "running", "Running": True, "Health": {"Status": status}}}
            return h._send(200, json.dumps(doc), "application/json", ping_headers)
        self.log("docker", action, name)
        if name == "qbittorrent_mouse":
            if action == "stop":
                self.qbit_available = False
            else:
                self.qbit_available = True
                self.qbit_restart()
        if name == "gluetun_mouse" and action == "restart" and self.port_after_restart is not None:
            self.ports = [self.port_after_restart]
        h._send(204, headers=ping_headers)
