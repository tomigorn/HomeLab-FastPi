"""Avatar picker: public gallery images + forward-auth protected picker/API."""
import gzip, hashlib, hmac, json, os, pathlib, re, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import core
import pickqueue
from authentik_api import AuthentikError, Client

APP = pathlib.Path(__file__).resolve().parent
# Avatars marked "pack": "local" are third-party art kept out of git in
# app/img-local/; the rest are committed in app/img/.
PACK_DIRS = {None: "img", "local": "img-local"}
GALLERY, GROUPS, IDS, FILES = [], [], set(), {}
# Gallery thumbnails built into the image (scripts/build_thumbs.py): id -> content hash, file name -> path.
THUMBS, THUMB_FILES = {}, {}
THUMB_RE = re.compile(r"[a-z0-9-]+\.[0-9a-f]{10}\.(160|320)\.webp")
THUMB_CACHE = "private, max-age=31536000, immutable"
GZIP_TYPES = ("text/html; charset=utf-8", "application/json")


def load(app_dir=APP):
    """Load the gallery, hiding avatars (and then-empty rows) whose image file is
    missing - e.g. a fresh clone without the local pack."""
    global GALLERY, GROUPS, IDS, FILES, THUMBS, THUMB_FILES
    app_dir = pathlib.Path(app_dir)
    files = {}
    for g in json.loads((app_dir / "gallery.json").read_text()):
        path = app_dir / PACK_DIRS.get(g.get("pack"), "img") / f"{g['id']}.png"
        if path.is_file():
            files[g["id"]] = (g, path)
    GALLERY = [g for g, _ in files.values()]
    shown = {g["group"] for g in GALLERY}
    GROUPS = [r for r in json.loads((app_dir / "groups.json").read_text()) if r["id"] in shown]
    IDS = set(files)
    FILES = {aid: path for aid, (_, path) in files.items()}
    manifest = app_dir / "thumbs" / "thumbs.json"
    THUMBS = {aid: h for aid, h in (json.loads(manifest.read_text()) if manifest.is_file() else {}).items()
              if aid in IDS}
    THUMB_FILES = {}
    for aid, h in THUMBS.items():
        for w in (160, 320):
            name = f"{aid}.{h}.{w}.webp"
            if (app_dir / "thumbs" / name).is_file():
                THUMB_FILES[name] = (aid, app_dir / "thumbs" / name)


load()
INDEX = (APP / "static" / "index.html").read_bytes()
INDEX_GZ = gzip.compress(INDEX, 9)
# Tab icons: static, public like the images (they show no user data).
ICONS = {"/favicon.svg": ("favicon.svg", "image/svg+xml"), "/favicon-32.png": ("favicon-32.png", "image/png"),
         "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png")}
ICONS = {path: ((APP / "static" / name).read_bytes(), ctype) for path, (name, ctype) in ICONS.items()}
VERSION = (APP / "VERSION").read_text().strip() if (APP / "VERSION").exists() else "dev"

_cfg = {"client": None, "base": None, "secret": None, "queue": None}
_pick_lock = threading.Lock()  # serialises check+write => uniqueness holds

# Images reached from outside (no LAN header): a picked one is public, the rest need a login session.
PICKED_TTL = 30
SESSION_TTL = 60
SESSION_MAX = 1000
_picked = {"ids": None, "at": 0.0}
_picked_lock = threading.Lock()
_sessions = {}
_sessions_lock = threading.Lock()


def configure(client, base, secret=None, queue=None):
    _cfg["client"], _cfg["base"], _cfg["secret"], _cfg["queue"] = client, base.rstrip("/"), secret, queue
    _picked.update(ids=None, at=0.0)
    with _sessions_lock:
        _sessions.clear()


def _set_picked(users):
    _picked.update(ids=set(core.picked_ids(users, _cfg["base"])), at=time.monotonic())


def picked_ids():
    """Avatar ids someone holds right now; on an Authentik error the last known set (empty if none)."""
    with _picked_lock:
        if _picked["ids"] is None or time.monotonic() - _picked["at"] > PICKED_TTL:
            try:
                _set_picked(_cfg["client"].list_users())
            except AuthentikError as e:
                print(f"picked set: {e}", flush=True)
                _picked["at"] = time.monotonic()
                if _picked["ids"] is None:
                    _picked["ids"] = set()
        return _picked["ids"]


def _session_cookie(header):
    for part in (header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == "authentik_session":
            return value.strip()
    return ""


def session_valid(cookie):
    """Cached positive answers only, keyed by a hash so the cookie itself is never kept."""
    if not cookie:
        return False
    key = hashlib.sha256(cookie.encode()).hexdigest()
    now = time.monotonic()
    with _sessions_lock:
        if _sessions.get(key, 0) > now:
            return True
    if not _cfg["client"].session_valid(cookie):
        return False
    with _sessions_lock:
        if len(_sessions) >= SESSION_MAX:
            for k in [k for k, t in _sessions.items() if t <= now] or list(_sessions)[:SESSION_MAX // 2]:
                del _sessions[k]
        _sessions[key] = now + SESSION_TTL
    return True


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Handler(BaseHTTPRequestHandler):
    timeout = 10
    server_version = "avatar-picker"
    sys_version = ""

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", cache=None, head=False):
        if isinstance(body, (dict, list)):
            body, ctype = json.dumps(body).encode(), "application/json"
        elif isinstance(body, str):
            body = body.encode()
        zipped = ctype in GZIP_TYPES and len(body) > 1024 and "gzip" in (self.headers.get("Accept-Encoding") or "")
        if zipped:
            body = INDEX_GZ if body is INDEX else gzip.compress(body, 6)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if ctype in GZIP_TYPES:
            self.send_header("Vary", "Accept-Encoding")
        if zipped:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", cache or "no-store")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def log_request(self, code="-", size="-"):
        if self.path.split("?", 1)[0] != "/healthz":
            super().log_request(code, size)

    def _caller(self):
        v = (self.headers.get("X-authentik-username") or "").strip()
        try:  # http.server decodes headers as latin-1; undo it for UTF-8 names
            v = v.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return v or None

    def _secret_ok(self):
        expected = _cfg["secret"]
        if expected is None:
            return True
        got = self.headers.get("X-Picker-Secret") or ""
        return hmac.compare_digest(got.encode(), expected.encode())

    def _public(self, path, head=False):
        """healthz / img / tab icons: returns True if handled."""
        if path == "/healthz":
            self._send(200, "ok", head=head)
            return True
        if path in ICONS:
            body, ctype = ICONS[path]
            self._send(200, body, ctype, cache="public, max-age=86400", head=head)
            return True
        if path.startswith("/img/") and path.endswith(".png"):
            aid = path[len("/img/"):-len(".png")]
            self._image(aid, FILES.get(aid), "image/png", head)
            return True
        if path.startswith("/thumb/"):
            name = path[len("/thumb/"):]
            aid, file = THUMB_FILES.get(name, (None, None)) if THUMB_RE.fullmatch(name) else (None, None)
            self._image(aid or name.split(".", 1)[0], file, "image/webp", head, thumb=True)
            return True
        return False

    def _image(self, aid, file, ctype, head, thumb=False):
        """LAN router (header set by Traefik) or the picker page: every image. Anyone else:
        a picked image without login, every other one only with an Authentik session.
        Thumbnail URLs carry a content hash, so outside a public cache they never expire."""
        lan = self.headers.get("X-Avatar-Access") == "lan"
        if lan or (_cfg["secret"] and self._secret_ok()):
            if file is None:
                return self._send(404, "not found", head=head)
            cache = THUMB_CACHE if thumb else ("public, max-age=86400" if lan else "private, max-age=86400")
            return self._send(200, file.read_bytes(), ctype, cache=cache, head=head)
        if file is not None and aid in picked_ids():
            return self._send(200, file.read_bytes(), ctype, cache="public, max-age=300", head=head)
        try:
            ok = session_valid(_session_cookie(self.headers.get("Cookie")))
        except AuthentikError as e:
            self.log_error("session check: %s", e)
            return self._send(503, "Authentik unreachable", head=head)
        if not ok:
            return self._send(403, "forbidden", head=head)
        if file is None:
            return self._send(404, "not found", head=head)
        return self._send(200, file.read_bytes(), ctype, cache=THUMB_CACHE if thumb else "private, max-age=300", head=head)

    def do_HEAD(self):
        path = self.path.split("?", 1)[0]
        if not self._public(path, head=True):
            self._send(404, "not found", head=True)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if self._public(path):
            return
        if path in ("/", "/index.html") or path.startswith("/api/"):
            if not self._secret_ok():
                return self._send(403, "forbidden")
        caller = self._caller()
        if path in ("/", "/index.html"):
            return self._send(200, INDEX, "text/html; charset=utf-8") if caller else self._send(401, "login required")
        if path == "/api/state":
            if not caller:
                return self._send(401, {"error": "login required"})
            try:
                users = _cfg["client"].list_users()
            except AuthentikError as e:
                self.log_error("authentik: %s", e)
                return self._send(503, {"error": "Authentik unreachable"})
            avatars = core.gallery_state(GALLERY, users, _cfg["base"], caller)
            for a in avatars:
                if a["id"] in THUMBS:
                    a["thumb"] = f"thumb/{a['id']}.{THUMBS[a['id']]}"
            return self._send(200, {"user": caller, "version": VERSION, "groups": GROUPS, "avatars": avatars})
        return self._send(404, "not found")

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/pick":
            return self._send(404, "not found")
        if not self._secret_ok():
            return self._send(403, "forbidden")
        caller = self._caller()
        if not caller:
            return self._send(401, {"error": "login required"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if not 0 <= n <= 1024:
            return self._send(400, {"error": "bad request"})
        try:
            aid = json.loads(self.rfile.read(n) or b"{}").get("id")
        except (ValueError, AttributeError):
            aid = None
        if not isinstance(aid, str) or aid not in IDS:
            return self._send(400, {"error": "unknown avatar"})
        with _pick_lock:
            try:
                users = _cfg["client"].list_users()
                pk = core.check_pick(GALLERY, users, _cfg["base"], caller, aid)
                current = _cfg["client"].get_user(pk).get("attributes") or {}
                _cfg["client"].set_attributes(pk, core.merged_attributes(current, _cfg["base"], aid))
                with _picked_lock:
                    _picked.update(ids=None, at=0.0)
                if _cfg["queue"]:
                    try:
                        pickqueue.record(_cfg["queue"], caller, aid, _now())
                    except OSError as e:
                        self.log_error("queue: %s", e)
            except core.AvatarTaken:
                return self._send(409, {"error": "just taken - pick another"})
            except core.UnknownUser:
                return self._send(403, {"error": "unknown user"})
            except AuthentikError as e:
                self.log_error("authentik: %s", e)
                return self._send(503, {"error": "Authentik unreachable"})
        self.log_message("pick %s -> %s", caller, aid)
        return self._send(200, {"ok": True, "url": core.avatar_url(_cfg["base"], aid)})


def main():
    token = pathlib.Path(os.environ["AUTHENTIK_TOKEN_FILE"]).read_text().strip()
    secret = pathlib.Path(os.environ["PICKER_SECRET_FILE"]).read_text().strip()
    if not secret:
        raise SystemExit("PICKER_SECRET_FILE is empty")
    queue = os.environ.get("QUEUE_FILE") or None
    client = Client(os.environ["AUTHENTIK_URL"], token)
    configure(client, os.environ["PUBLIC_BASE_URL"], secret, queue)
    if queue:
        try:
            added = pickqueue.backfill(queue, client.list_users(), _cfg["base"], _now())
            print(f"queue: backfilled {len(added)} pick(s)", flush=True)
        except (AuthentikError, OSError) as e:
            print(f"queue: backfill skipped: {e}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
