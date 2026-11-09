"""Fake Authentik for the black-box suite: users API (Bearer token), users/me (session cookie), control API under /_mock/.

Usage: mock_authentik.py PORT TOKEN
"""
import copy
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

BASE = "https://sso.example.com/avatar-img"
PAGE = 2
USERS = [
    {"pk": 1, "username": "alice", "type": "internal", "attributes": {"avatar": f"{BASE}/img/alpha.png"}},
    {"pk": 2, "username": "bob", "type": "internal", "attributes": {"theme": "dark"}},
    {"pk": 3, "username": "svc-bot", "type": "service_account", "attributes": {"avatar": f"{BASE}/img/beta.png"}},
    {"pk": 4, "username": "jörg", "type": "external", "attributes": {}},
    {"pk": 5, "username": "carol", "type": "internal", "attributes": None},
    {"pk": 6, "username": "outsider", "type": "internal", "attributes": {"avatar": "https://elsewhere.example.com/img/gamma.png"}},
]
state = {"users": copy.deepcopy(USERS), "fail": set(), "log": [], "me_calls": {}}
lock = threading.Lock()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _authed(self):
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"null")

    def do_GET(self):
        u = urlsplit(self.path)
        if u.path == "/_mock/state":
            with lock:
                return self._json(200, {"users": state["users"], "log": state["log"], "me_calls": state["me_calls"]})
        if u.path == "/api/v3/core/users/me/":
            cookie = self.headers.get("Cookie") or ""
            if self.headers.get("Authorization"):
                return self._json(400, {"detail": "token must not be sent"})
            with lock:
                state["me_calls"][cookie] = state["me_calls"].get(cookie, 0) + 1
            if "me" in state["fail"] or cookie == "authentik_session=boom":
                return self._json(500, {"detail": "boom"})
            if cookie.startswith("authentik_session=valid"):
                return self._json(200, {"user": {"username": "someone"}})
            if cookie == "authentik_session=redirect":
                self.send_response(302)
                self.send_header("Location", "/_mock/state")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return self._json(403, {"detail": "not authenticated"})
        if not self._authed():
            return self._json(403, {"detail": "bad token"})
        if "list" in state["fail"]:
            return self._json(500, {"detail": "down"})
        if u.path == "/api/v3/core/users/":
            q = parse_qs(u.query)
            page = int(q.get("page", ["1"])[0])
            with lock:
                state["log"].append(["GET", self.path])
                users = state["users"]
                chunk = users[(page - 1) * PAGE: page * PAGE]
                nxt = page + 1 if page * PAGE < len(users) else 0
            return self._json(200, {"pagination": {"next": nxt, "current": page}, "results": chunk})
        if u.path.startswith("/api/v3/core/users/"):
            pk = int(u.path.split("/")[5])
            with lock:
                for x in state["users"]:
                    if x["pk"] == pk:
                        return self._json(200, x)
            return self._json(404, {"detail": "not found"})
        self._json(404, {"detail": "not found"})

    def do_PATCH(self):
        if not self._authed():
            return self._json(403, {"detail": "bad token"})
        if "patch" in state["fail"]:
            return self._json(500, {"detail": "down"})
        pk = int(urlsplit(self.path).path.split("/")[5])
        body = self._body()
        with lock:
            state["log"].append(["PATCH", self.path, body])
            for x in state["users"]:
                if x["pk"] == pk:
                    x["attributes"] = body["attributes"]
                    return self._json(200, x)
        self._json(404, {"detail": "not found"})

    def do_POST(self):
        u = urlsplit(self.path)
        body = self._body()
        with lock:
            if u.path == "/_mock/fail":
                state["fail"] = set(body)
            elif u.path == "/_mock/reset":
                state.update(users=copy.deepcopy(USERS), fail=set(), log=[], me_calls={})
            elif u.path == "/_mock/clear-log":
                state.update(log=[], me_calls={})
            else:
                return self._json(404, {})
        self._json(200, {"ok": True})


if __name__ == "__main__":
    TOKEN = sys.argv[2]
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
