"""Fakes for everything the importer talks to: qBittorrent, Audiobookshelf, AudioBookRequest, Prowlarr, Audible. Nothing here reaches the network."""
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Call:
    def __init__(self, method, path, headers, body):
        self.method, self.path, self.headers, self.body = method, path, headers, body
        split = urllib.parse.urlsplit(path)
        self.route = split.path
        self.query = urllib.parse.parse_qs(split.query, keep_blank_values=True)

    def json(self):
        return json.loads(self.body) if self.body else None

    def __repr__(self):
        return f"{self.method} {self.path}"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _serve(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        call = Call(self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body)
        with self.server.lock:
            self.server.app.calls.append(call)
            status, ctype, out, extra = self.server.app.respond(call)
        if isinstance(out, (dict, list)):
            out = json.dumps(out).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(out)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _serve

    def log_message(self, *args):
        pass


class Mock:
    """One fake per upstream. respond(call) -> (status, content_type, body, extra_headers)."""

    def __init__(self):
        self.calls = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.app = self
        self.server.lock = threading.RLock()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def reset(self):
        self.calls.clear()

    def named(self, method, route):
        return [c for c in self.calls if c.method == method and c.route == route]

    def respond(self, call):
        return 404, "text/plain", b"mock: no route", None


class Qbit(Mock):
    """qBittorrent Web API: cookie login, torrents/info, torrents/export."""

    def __init__(self, password="qbit-secret"):
        super().__init__()
        self.password = password
        self.sessions = set()
        self.torrents = []
        self.export_bytes = b"d8:announce3:xyze"

    def logged_in(self, call):
        cookie = call.headers.get("cookie", "")
        return any(f"SID={s}" in cookie for s in self.sessions)

    def respond(self, call):
        if call.route == "/api/v2/auth/login" and call.method == "POST":
            form = urllib.parse.parse_qs(call.body.decode())
            if form.get("password", [""])[0] == self.password:
                sid = f"s{len(self.calls)}"
                self.sessions.add(sid)
                return 200, "text/plain", b"Ok.", {"Set-Cookie": f"SID={sid}; HttpOnly; path=/"}
            return 200, "text/plain", b"Fails.", None
        if not self.logged_in(call):
            return 403, "text/plain", b"Forbidden", None
        if call.route == "/api/v2/torrents/info":
            found = self.torrents
            if "category" in call.query:
                found = [t for t in found if t.get("category") == call.query["category"][0]]
            if "hashes" in call.query:
                wanted = call.query["hashes"][0].split("|")
                found = [t for t in found if t["hash"] in wanted]
            return 200, "application/json", found, None
        if call.route == "/api/v2/torrents/export":
            return 200, "application/x-bittorrent", self.export_bytes, None
        return 404, "text/plain", b"not found", None


class Abs(Mock):
    """Audiobookshelf: libraries, items, users, search, match, scan, cover."""

    def __init__(self, key="abs-importer-key"):
        super().__init__()
        self.key = key
        self.libraries = [
            {"id": "en", "name": "[EN] Audiobooks", "mediaType": "book", "folders": [{"fullPath": "/audiobooks/EN"}]},
            {"id": "de", "name": "[DE] Hörbücher", "mediaType": "book", "folders": [{"fullPath": "/audiobooks/DE"}]},
            {"id": "other", "name": "Other", "mediaType": "book", "folders": [{"fullPath": "/audiobooks/Other"}]},
            {"id": "pod", "name": "Podcasts", "mediaType": "podcast", "folders": [{"fullPath": "/podcasts"}]},
        ]
        self.items = {}            # library id -> minified items
        self.users = []
        self.search = {}           # library id -> search result dict
        self.details = {}          # item id -> full item
        self.author_match = {"author": {"asin": "AU1", "imagePath": "/metadata/authors/x.jpg"}}
        self.match_result = {}
        self.cover = b"RIFF\x00\x00\x00\x00WEBPVP8 "
        self.cover_status = 200
        self.scan_status = 200

    def respond(self, call):
        if call.headers.get("authorization", "") not in (f"Bearer {self.key}", "Bearer abr-readonly-key"):
            return 401, "application/json", {"error": "unauthorized"}, None
        parts = call.route.strip("/").split("/")
        if call.route == "/api/libraries" and call.method == "GET":
            return 200, "application/json", {"libraries": self.libraries}, None
        if parts[:2] == ["api", "libraries"] and len(parts) == 4:
            lib = parts[2]
            if parts[3] == "items":
                return 200, "application/json", {"results": self.items.get(lib, [])}, None
            if parts[3] == "search":
                return 200, "application/json", self.search.get(lib, {"book": [], "series": [], "authors": []}), None
            if parts[3] == "scan" and call.method == "POST":
                return self.scan_status, "application/json", {}, None
        if call.route == "/api/users":
            return 200, "application/json", {"users": self.users}, None
        if parts[:2] == ["api", "items"] and len(parts) == 3 and call.method == "GET":
            item = self.details.get(parts[2])
            return (200, "application/json", item, None) if item else (404, "application/json", {}, None)
        if parts[:2] == ["api", "items"] and len(parts) == 4:
            if parts[3] == "match" and call.method == "POST":
                return 200, "application/json", self.match_result, None
            if parts[3] == "cover":
                return self.cover_status, "image/webp", self.cover, None
        if parts[:2] == ["api", "authors"] and len(parts) == 4 and parts[3] == "match":
            return 200, "application/json", self.author_match, None
        return 404, "application/json", {}, None


class Abr(Mock):
    """AudioBookRequest's request lists."""

    def __init__(self, key="abr-importer-key"):
        super().__init__()
        self.key = key
        self.wishlist = []
        self.manual = []
        self.fail = False

    def respond(self, call):
        if self.fail:
            return 500, "text/plain", b"boom", None
        if call.headers.get("authorization") != f"Bearer {self.key}":
            return 401, "application/json", {"detail": "unauthorized"}, None
        if call.route == "/api/requests":
            return 200, "application/json", self.wishlist, None
        if call.route == "/api/requests/manual":
            return 200, "application/json", self.manual, None
        return 404, "application/json", {}, None


def release(title, date="2024-01-01T00:00:00Z", seeders=5, **extra):
    return dict({"guid": title + date, "title": title, "publishDate": date, "seeders": seeders, "indexerFlags": [],
                 "downloadUrl": "http://10.24.25.2:9697/1/download?apikey=k&link=x"}, **extra)


def mam(tid, title, date, seeders):
    return release(title, date + "T00:00:00Z", seeders, guid=f"https://www.myanonamouse.net/t/{tid}")


SENSE = [mam(572126, "Sense & Sensibility by Joanna Trollope [ENG / MP3]", "2019-12-02", 10),
         mam(51512, "Sense & Sensibility & Sea Monsters by Ben H Winters [ENG / MP3]", "2010-08-11", 5),
         mam(1039841, "Sense and Sensibility by Jane Austen [ENG / M4B]", "2024-05-29", 26),
         mam(472825, "Sense and Sensibility by Jane Austen [ENG / MP3]", "2018-11-06", 16),
         mam(804228, "Sense and Sensibility by Jane Austen [ENG / M4B]", "2022-02-22", 138),
         mam(1277153, "Sense and Sensibility by Jane Austen [ENG / M4B]", "2026-10-17", 27),
         mam(1167215, "Sense and Sensibility by Jane Austen [ENG / M4B]", "2025-07-23", 59),
         mam(220942, "BBC R4 CS - Sense and Sensibility by Jane Austen (Aug 2013) by Jane Austen, BBC Radio 4 [ENG / MP3]", "2014-12-06", 5),
         mam(942700, "Women, Work, and the Art of Savoir Faire: Business Sense and Sensibility by Mireille Guiliano [ENG / M4B]", "2023-06-28", 3)]
SAVAGE = [r for r in SENSE if r["guid"].endswith(("/472825", "/1039841"))]


class Prowlarr(Mock):
    """Prowlarr behind the pass-through: search (GET), grab (POST search), indexer read/write, and an echo route."""

    def __init__(self):
        super().__init__()
        self.results = lambda query: SAVAGE if query.endswith("Karen Savage") else SENSE
        self.search_status = 200
        self.grab_statuses = []        # popped per grab; empty = 200
        self.indexers = [{"id": 1, "name": "MyAnonamouse", "implementation": "MyAnonamouse",
                          "fields": [{"name": "useFreeleechWedge", "value": True}, {"name": "mamId", "value": "secret"}]}]

    def respond(self, call):
        if call.route == "/api/v1/search" and call.method == "GET":
            if self.search_status != 200:
                return self.search_status, "text/plain", b"search failed", None
            return 200, "application/json", self.results(call.query.get("query", [""])[0]), None
        if call.route == "/api/v1/search" and call.method == "POST":
            status = self.grab_statuses.pop(0) if self.grab_statuses else 200
            if status != 200:
                return status, "application/json", {"message": "grab failed"}, None
            return 200, "application/json", {"grabbed": call.json()}, None
        if call.route == "/api/v1/indexer" and call.method == "GET":
            return 200, "application/json", self.indexers, None
        if call.route.startswith("/api/v1/indexer/") and call.method == "PUT":
            body = call.json()
            self.indexers = [body if i["id"] == body["id"] else i for i in self.indexers]
            return 202, "application/json", body, None
        if call.route == "/api/v1/echo":
            return 200, "application/json", {"apikey": call.headers.get("x-api-key"), "path": call.path,
                                             "accept": call.headers.get("accept")}, None
        if call.route == "/api/v1/unauthorized":
            return 401, "text/plain", b"Unauthorized", None
        return 404, "application/json", {}, None

    def wedge(self):
        return next(f["value"] for f in self.indexers[0]["fields"] if f["name"] == "useFreeleechWedge")


class Audible(Mock):
    """api.audible.<region>/1.0/catalog/products/<asin>, routed as /audible.<region>/... (Rust: AUDIBLE_BASE)."""

    def __init__(self):
        super().__init__()
        self.products = {}

    def respond(self, call):
        parts = call.route.strip("/").split("/")
        if len(parts) == 5 and parts[1:4] == ["1.0", "catalog", "products"]:
            product = self.products.get(parts[4])
            return 200, "application/json", {"product": product or {}}, None
        if parts[-1] == "authors":
            return 200, "application/json", [], None
        return 404, "application/json", {}, None
