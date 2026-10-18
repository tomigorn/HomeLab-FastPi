"""Avatar picker: public gallery images + forward-auth protected picker/API."""
import json, os, pathlib, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import core
from authentik_api import AuthentikError, Client

APP = pathlib.Path(__file__).resolve().parent
GALLERY = json.loads((APP / "gallery.json").read_text())
IDS = {g["id"] for g in GALLERY}
INDEX = (APP / "static" / "index.html").read_bytes()
VERSION = (APP / "VERSION").read_text().strip() if (APP / "VERSION").exists() else "dev"

_cfg = {"client": None, "base": None}
_pick_lock = threading.Lock()  # serialises check+write => uniqueness holds


def configure(client, base):
    _cfg["client"], _cfg["base"] = client, base.rstrip("/")


class Handler(BaseHTTPRequestHandler):
    timeout = 10
    server_version = "avatar-picker"
    sys_version = ""

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", cache=None):
        if isinstance(body, (dict, list)):
            body, ctype = json.dumps(body).encode(), "application/json"
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", cache or "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _caller(self):
        return (self.headers.get("X-authentik-username") or "").strip() or None

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            return self._send(200, "ok")
        if path.startswith("/img/") and path.endswith(".png"):
            aid = path[len("/img/"):-len(".png")]
            if aid not in IDS:
                return self._send(404, "not found")
            return self._send(200, (APP / "img" / f"{aid}.png").read_bytes(),
                              "image/png", cache="public, max-age=86400")
        caller = self._caller()
        if path in ("/", "/index.html"):
            return self._send(200, INDEX, "text/html; charset=utf-8") if caller else self._send(401, "login required")
        if path == "/api/state":
            if not caller:
                return self._send(401, {"error": "login required"})
            try:
                users = _cfg["client"].list_users()
            except AuthentikError:
                return self._send(503, {"error": "Authentik unreachable"})
            return self._send(200, {"user": caller, "version": VERSION,
                                    "avatars": core.gallery_state(GALLERY, users, _cfg["base"], caller)})
        return self._send(404, "not found")

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/pick":
            return self._send(404, "not found")
        caller = self._caller()
        if not caller:
            return self._send(401, {"error": "login required"})
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 1024)
            aid = json.loads(self.rfile.read(n) or b"{}").get("id")
        except (ValueError, AttributeError):
            aid = None
        if not isinstance(aid, str) or aid not in IDS:
            return self._send(400, {"error": "unknown avatar"})
        with _pick_lock:
            try:
                users = _cfg["client"].list_users()
                pk = core.check_pick(GALLERY, users, _cfg["base"], caller, aid)
                current = next(u for u in users if u["pk"] == pk).get("attributes") or {}
                _cfg["client"].set_attributes(pk, core.merged_attributes(current, _cfg["base"], aid))
            except core.AvatarTaken:
                return self._send(409, {"error": "just taken - pick another"})
            except core.UnknownUser:
                return self._send(403, {"error": "unknown user"})
            except AuthentikError:
                return self._send(503, {"error": "Authentik unreachable"})
        self.log_message("pick %s -> %s", caller, aid)
        return self._send(200, {"ok": True, "url": core.avatar_url(_cfg["base"], aid)})


def main():
    token = pathlib.Path(os.environ["AUTHENTIK_TOKEN_FILE"]).read_text().strip()
    configure(Client(os.environ["AUTHENTIK_URL"], token), os.environ["PUBLIC_BASE_URL"])
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
