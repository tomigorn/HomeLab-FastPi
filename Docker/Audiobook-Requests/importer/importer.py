"""Copies finished AudioBookRequest downloads (qBittorrent category abr) into the Audiobookshelf library, then scans it."""
import copy
import datetime
import json
import logging
import os
import re
import shutil
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from naming import Book, book_dir, language_folder, mam_language
from ranking import for_abr, prefs_from_product

ENV = os.environ.get
QBIT_URL = ENV("QBIT_URL", "http://10.24.25.2:8080")
CATEGORY = ENV("CATEGORY", "abr")
LIBRARY = Path(ENV("LIBRARY", "/library"))
STATE = Path(ENV("STATE", "/data/jobs.json"))
ABS_URL = ENV("ABS_URL", "https://audiobookshelf.holy-grail.ch")
ABS_FOLDER = ENV("ABS_FOLDER", "/audiobooks")   # ABS's mount of LIBRARY
AUDIBLE_REGIONS = ENV("AUDIBLE_REGIONS", "com,de,co.uk").split(",")
POLL_SECONDS = int(ENV("POLL_SECONDS", "60"))
GIVE_UP_DAYS = int(ENV("GIVE_UP_DAYS", "14"))
MERGE_WAIT_HOURS = int(ENV("MERGE_WAIT_HOURS", "48"))
MATCH_GIVE_UP_HOURS = int(ENV("MATCH_GIVE_UP_HOURS", "24"))
PROWLARR_URL = ENV("PROWLARR_URL", "http://10.24.25.2:9697")
PROXY_BASE = ENV("PROXY_BASE", "http://audiobook-importer:8000/prowlarr")
QUOTA_BOOKS = int(ENV("QUOTA_BOOKS", "5"))
QUOTA_DAYS = int(ENV("QUOTA_DAYS", "7"))
QUOTA_LEDGER = Path(ENV("QUOTA_LEDGER", "/data/quota.json"))
# Only these neighbours on traefik_mouse may call these paths: the username header is trusted only from books-proxy, the .torrent carries the MAM passkey.
CALLERS = {"/quota": (ENV("BOOKS_PROXY_IP", "10.24.25.6"),), "/all-requests": (ENV("BOOKS_PROXY_IP", "10.24.25.6"),),
           "/prowlarr/torrent": (ENV("ABR_IP", "10.24.25.4"), ENV("ABR_HOST", "audiobookrequest"))}
ABR_URL = ENV("ABR_URL", "http://audiobookrequest:8000")
PROVIDERS = {"com": ("audible", "us"), "de": ("audible.de", "de"), "co.uk": ("audible.uk", "uk")}
AUDIO = {".mp3", ".m4a", ".m4b", ".aac", ".flac", ".ogg", ".opus", ".wma", ".wav"}

log = logging.getLogger("importer")
lock = threading.Lock()


def parse_webhook(body):
    h = str(body.get("hash", "")).strip().lower()
    # ABR sends no hash when an admin picks the source by hand: bind() matches the torrent later.
    unbound = h in ("", "{torrentinfohash}")
    if not unbound and not re.fullmatch(r"[0-9a-f]{40}", h):
        raise ValueError("hash must be 40 hex characters")

    def value(key):
        v = str(body.get(key) or "").strip()
        return "" if re.fullmatch(r"\{\w+\}", v) else v

    return {"hash": None if unbound else h, "asin": value("asin") or None, "title": value("title"),
            "authors": [a.strip() for a in value("authors").split(",") if a.strip()],
            "source": value("source"), "indexer": value("indexer"), "state": "unbound" if unbound else "pending",
            "added": time.time()}


def _ts(value):
    try:
        return datetime.datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return 0.0


def _resolve(name):
    try:
        return socket.gethostbyname_ex(name)[2]
    except OSError:
        return []


def caller_ok(path, client, resolve=_resolve):
    """ABR also calls over the egress network, whose address is dynamic: names are resolved per call."""
    want = CALLERS.get(urllib.parse.urlsplit(path).path)
    if want is None:
        return True
    return any(client == w or (not w[0].isdigit() and client in resolve(w)) for w in want)


def quota_entries(wishlist, manual):
    """ABR's live requests as {user|book: {user, at}}."""
    out = {}
    for w in wishlist:
        asin = (w.get("book") or {}).get("asin")
        for r in w.get("requests") or []:
            out[f"{r.get('user_username')}|{asin}"] = {"user": r.get("user_username"), "at": _ts(r.get("updated_at"))}
    for i, m in enumerate(manual):
        out[f"{m.get('user_username')}|manual-{m.get('id') or i}"] = {"user": m.get("user_username"), "at": _ts(m.get("updated_at"))}
    return out


def merge_ledger(ledger, entries, now):
    """Every request ever seen in the window, so deleting a request does not give its slot back. First sighting wins."""
    since = now - QUOTA_DAYS * 86400
    merged = {k: v for k, v in ledger.items() if v["at"] >= since}
    for k, v in entries.items():
        if v["at"] >= since:
            merged.setdefault(k, v)
    return merged


def quota_ok(wishlist, manual, user, now, ledger=None):
    """At most QUOTA_BOOKS requests per user in a rolling QUOTA_DAYS window, for everyone (admins too)."""
    if not user:
        return False
    entries = merge_ledger(ledger or {}, quota_entries(wishlist, manual), now)
    return sum(1 for v in entries.values() if v["user"] == user) < QUOTA_BOOKS


def _status(downloaded, job_state):
    if job_state in ("pending", "unbound", "merge-wait"):
        return "downloading"
    if job_state in ("done", "exists") or downloaded:
        return "in library"
    return "open"


def all_requests(wishlist, manual, jobs):
    """Everyone's requests for the read-only "All requests" page (owner 2026-10-27: with names), newest first."""
    state = {j.get("asin"): j.get("state") for j in jobs.values() if j.get("asin")}
    rows = []
    for w in wishlist:
        b = w["book"]
        for r in w.get("requests") or []:
            rows.append({"title": b.get("title"), "author": ", ".join(b.get("authors") or []), "cover": b.get("cover_image"),
                         "requested_by": r.get("user_username"), "requested": r.get("updated_at"),
                         "status": _status(b.get("downloaded"), state.get(b.get("asin")))})
    for m in manual:
        rows.append({"title": m.get("title"), "author": ", ".join(m.get("authors") or []), "cover": None,
                     "requested_by": m.get("user_username"), "requested": m.get("updated_at"),
                     "status": _status(m.get("downloaded"), None)})
    return sorted(rows, key=lambda r: r["requested"] or "", reverse=True)


def with_wedge(indexer, on):
    out = copy.deepcopy(indexer)
    for f in out["fields"]:
        if f["name"] == "useFreeleechWedge":
            f["value"] = on
    return out


def bind(job, torrents, known, window=600):
    """Hash of the abr torrent added closest after the webhook (within window seconds) that no job owns yet."""
    fresh = [t for t in torrents if t.get("category") == CATEGORY and t["hash"] not in known
             and -60 <= t["added_on"] - job["added"] <= window]
    return min(fresh, key=lambda t: abs(t["added_on"] - job["added"]))["hash"] if fresh else None


def resolve_book(job, product):
    language = mam_language(job.get("source")) or "Other"
    if product and product.get("title"):
        series = (product.get("series") or [{}])[0]
        return Book(product["title"], [a["name"] for a in product.get("authors") or []] or job.get("authors") or [],
                    series.get("title"), series.get("sequence"), language_folder(product.get("language")) or language)
    return Book(job.get("title") or "", job.get("authors") or [], None, None, language)


def needs_merge(names):
    return sum(Path(n).suffix.lower() in AUDIO for n in names) >= 2


def copy_into(src, library, rel):
    dest = library / rel
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(str(dest))
    tmp = dest.parent / f".{dest.name}.importing"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        # M4b-Auto-Merge works per folder: CD1/01.mp3 becomes "CD1 - 01.mp3" (order kept, names otherwise original).
        tmp.mkdir()
        for f in sorted(p for p in src.rglob("*") if p.is_file()):
            shutil.copy2(f, tmp / " - ".join(f.relative_to(src).parts))
    else:
        tmp.mkdir()
        shutil.copy2(src, tmp / src.name)
    if dest.exists():
        dest.rmdir()
    tmp.rename(dest)
    return dest


def match_body(book, asin, region):
    body = {"provider": PROVIDERS.get(region, PROVIDERS["com"])[0], "title": book.title,
            "author": book.authors[0] if book.authors else "", "overrideCover": True, "overrideDetails": True}
    if asin:
        body["asin"] = asin
    return {k: body[k] for k in ("provider", "asin", "title", "author", "overrideCover", "overrideDetails") if k in body}


def author_match_body(name, region):
    return {"q": name, "region": PROVIDERS.get(region, PROVIDERS["com"])[1]}


def other_author_asins(found, name, current):
    """Audible lists one author under several ASINs, often only one with a picture: the other ASINs of the same name, in order."""
    def key(n):
        return " ".join((n or "").lower().split())
    out = []
    for a in found:
        if key(a.get("name")) == key(name) and a.get("asin") and a["asin"] != current and a["asin"] not in out:
            out.append(a["asin"])
    return out


def merge_searches(results):
    return {"book": [b for r in results for b in (r.get("book") or [])]}


def book_library_ids(libs):
    return [lib["id"] for lib in libs if lib.get("mediaType") == "book"]


def abs_path(rel):
    return f"{ABS_FOLDER}/{rel}"


def library_for(libs, rel):
    """ABS has one library per language folder (/audiobooks/EN, /DE, /Other)."""
    path = abs_path(rel)
    for lib in libs:
        if any(path.startswith(f["fullPath"].rstrip("/") + "/") for f in lib["folders"]):
            return lib["id"]
    return None


def http_json(url, data=None, headers=None, opener=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with (opener or urllib.request.build_opener()).open(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw.strip() else None


def audible(asin):
    if not asin or not re.fullmatch(r"[0-9A-Z]{10}", asin):
        return None
    for region in AUDIBLE_REGIONS:
        url = (f"https://api.audible.{region}/1.0/catalog/products/{asin}"
               "?response_groups=series,contributors,product_desc,product_attrs,product_extended_attrs")
        try:
            product = (http_json(url) or {}).get("product") or {}
        except (urllib.error.URLError, ValueError) as e:
            log.warning("audible %s %s: %s", region, asin, e)
            continue
        if product.get("title"):
            return product, region
    return None, None


class Qbit:
    def __init__(self, password):
        self.password = password
        self.opener = None

    def login(self):
        jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.opener.addheaders = [("Referer", QBIT_URL)]
        data = urllib.parse.urlencode({"username": ENV("QBIT_USER", "admin"), "password": self.password}).encode()
        self.opener.open(QBIT_URL + "/api/v2/auth/login", data=data, timeout=30).read()
        if not any("SID" in c.name for c in jar):
            raise RuntimeError("qBittorrent login failed")

    def category(self):
        for attempt in (1, 2):
            try:
                if not self.opener:
                    self.login()
                return http_json(f"{QBIT_URL}/api/v2/torrents/info?category={CATEGORY}", opener=self.opener) or []
            except urllib.error.HTTPError as e:
                if e.code != 403 or attempt == 2:
                    raise
                self.opener = None

    def torrent(self, h):
        for attempt in (1, 2):
            try:
                if not self.opener:
                    self.login()
                found = http_json(f"{QBIT_URL}/api/v2/torrents/info?hashes={h}", opener=self.opener)
                return found[0] if found else None
            except urllib.error.HTTPError as e:
                if e.code != 403 or attempt == 2:
                    raise
                self.opener = None


class Abs:
    def __init__(self, key_file):
        self.key_file = key_file

    @property
    def key(self):
        return secret(self.key_file)

    def headers(self):
        return {"Authorization": f"Bearer {self.key}"}

    def library(self, rel):
        lib = library_for(http_json(f"{ABS_URL}/api/libraries", headers=self.headers())["libraries"], rel)
        if not lib:
            raise RuntimeError(f"no ABS library holds {abs_path(rel)}")
        return lib

    def post(self, path, body):
        data = json.dumps(body).encode()
        return http_json(f"{ABS_URL}{path}", data=data, headers=dict(self.headers(), **{"Content-Type": "application/json"}))

    def find_item(self, rel, title):
        q = urllib.parse.quote(title)
        found = http_json(f"{ABS_URL}/api/libraries/{self.library(rel)}/search?q={q}&limit=25", headers=self.headers())
        for hit in found.get("book") or []:
            if hit["libraryItem"]["path"] == abs_path(rel):
                return hit["libraryItem"]["id"]
        return None

    def match(self, job):
        """Audible match (details + cover), then every author (image + description). Returns False until ABS has the item."""
        book = Book(job["book"]["title"], job["book"]["authors"])
        item_id = self.find_item(job["dest"], book.title)
        if not item_id:
            return False
        result = self.post(f"/api/items/{item_id}/match", match_body(book, job.get("asin"), job.get("region"))) or {}
        if result.get("warning"):
            log.warning("ABS match %s: %s", job["dest"], result["warning"])
        item = http_json(f"{ABS_URL}/api/items/{item_id}", headers=self.headers())
        for author in item["media"]["metadata"].get("authors") or []:
            try:
                self.match_author(author, job.get("region"))
            except urllib.error.HTTPError as e:
                log.warning("ABS author match %s: HTTP %s", author["name"], e.code)
        log.info("ABS matched %s", job["dest"])
        return True

    def match_author(self, author, region):
        body = author_match_body(author["name"], region)
        found = (self.post(f"/api/authors/{author['id']}/match", body) or {}).get("author") or {}
        if found.get("imagePath"):
            return
        q = urllib.parse.urlencode({"name": author["name"], "region": body["region"]})
        best = found if found.get("description") else None
        try:
            candidates = http_json(f"https://api.audnex.us/authors?{q}") or []
        except (urllib.error.URLError, ValueError) as e:
            log.warning("audnexus author search %s: %s", author["name"], e)
            candidates = []
        for asin in other_author_asins(candidates, author["name"], found.get("asin")):
            found = (self.post(f"/api/authors/{author['id']}/match", {"asin": asin, "region": body["region"]}) or {}).get("author") or {}
            if found.get("imagePath"):
                log.info("author image for %s via %s", author["name"], asin)
                return
            best = best or (found if found.get("description") else None)
        if best and best.get("asin") != found.get("asin"):
            self.post(f"/api/authors/{author['id']}/match", {"asin": best["asin"], "region": body["region"]})
        log.info("no author image on Audible for %s (kept %s)", author["name"], (best or found).get("asin"))

    def scan(self, rel):
        req = urllib.request.Request(f"{ABS_URL}/api/libraries/{self.library(rel)}/scan", data=b"", method="POST",
                                     headers=self.headers())
        urllib.request.urlopen(req, timeout=60).read()
        log.info("ABS library scan started")


def load():
    try:
        return json.loads(STATE.read_text())
    except FileNotFoundError:
        return {}


def save(jobs):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(jobs, indent=1, ensure_ascii=False))
    tmp.replace(STATE)


def step(job, qbit, abs_, now):
    if job["state"] == "pending":
        t = qbit.torrent(job["hash"])
        if not t:
            if now - job["added"] > GIVE_UP_DAYS * 86400:
                job["state"] = "failed"
                job["error"] = "torrent never appeared in qBittorrent"
            return
        if t.get("category") != CATEGORY:
            job.update(state="failed", error=f"category is {t.get('category')!r}, not {CATEGORY!r}")
            return
        if t.get("progress", 0) < 1:
            return
        product, region = audible(job.get("asin"))
        book = resolve_book(job, product)
        rel = book_dir(book)
        job.update(region=region, book={"title": book.title, "authors": book.authors})
        try:
            dest = copy_into(Path(t["content_path"]), LIBRARY, rel)
        except FileExistsError:
            job.update(state="exists", dest=rel)
            log.warning("%s already in the library, not overwritten", rel)
            return
        names = [p.name for p in dest.rglob("*") if p.is_file()]
        job.update(state="merge-wait" if needs_merge(names) else "done", dest=rel, imported=now)
        log.info("imported %s (%d files)", rel, len(names))
    elif job["state"] == "merge-wait":
        dest = LIBRARY / job["dest"]
        names = [p.name for p in dest.rglob("*") if p.is_file()]
        if not needs_merge(names) or now - job["imported"] > MERGE_WAIT_HOURS * 3600:
            job["state"] = "done"
            job.pop("scanned", None)
            log.info("merged or waited long enough: %s", job["dest"])


def match_step(job, abs_, now):
    # Only after M4b-Auto-Merge is through (state done), so ABS never indexes the loose parts.
    if job["state"] != "done" or job.get("matched") or not abs_.key or "book" not in job:
        return
    if not job.get("scanned"):
        abs_.scan(job["dest"])
        job["scanned"] = now
        return
    if job["state"] == "done" and abs_.match(job):
        job["matched"] = now
    elif job["state"] == "done" and now - job["scanned"] > MATCH_GIVE_UP_HOURS * 3600:
        job["matched"] = "gave up: item never appeared in ABS"


def poll(qbit, abs_):
    while True:
        with lock:
            jobs = load()
            for key, job in list(jobs.items()):
                if job["state"] == "unbound":
                    try:
                        h = bind(job, qbit.category(), set(jobs))
                    except Exception as e:  # noqa: BLE001
                        log.error("bind %s: %s", key, e)
                        h = None
                    if h:
                        jobs[h] = dict(jobs.pop(key), hash=h, state="pending")
                        log.info("bound %s to %s", job["title"], h[:8])
                    elif time.time() - job["added"] > 3600:
                        job["state"] = "failed"
                        job["error"] = "no new abr torrent appeared for this request"
            for job in jobs.values():
                try:
                    if job["state"] in ("pending", "merge-wait"):
                        step(job, qbit, abs_, time.time())
                    match_step(job, abs_, time.time())
                except Exception as e:  # noqa: BLE001  one bad job must not stop the others
                    log.error("%s: %s: %s", job["hash"], type(e).__name__, e)
            save(jobs)
        try:
            snapshot_quota()
        except (urllib.error.URLError, ValueError, OSError) as e:
            log.error("quota snapshot: %s", e)
        time.sleep(POLL_SECONDS)


class Requests:
    """Preferences of the book behind a Prowlarr search: language + abridged from its Audible edition (ABR request)."""

    def __init__(self, key):
        self.key = key
        self.cache = {}

    def prefs(self, query):
        if query in self.cache:
            return self.cache[query]
        product = None
        if self.key:
            try:
                wishlist = http_json(f"{ABR_URL}/api/requests", headers={"Authorization": f"Bearer {self.key}"})
                asin = next((w["book"]["asin"] for w in wishlist if w["book"]["title"] == query), None)
                product = audible(asin)[0]
            except (urllib.error.URLError, ValueError, KeyError) as e:
                log.warning("request lookup for %r: %s", query, e)
        self.cache[query] = prefs = prefs_from_product(product)
        return prefs


REQUESTS = Requests("")


def prowlarr(method, path, headers, data=None):
    req = urllib.request.Request(PROWLARR_URL + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "application/json")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "text/plain")


def grab_without_wedge(headers, data):
    """A wedge grab failed (e.g. no wedges left): retry once as a normal download, then switch the wedge back on."""
    key = {"X-Api-Key": headers.get("X-Api-Key", ""), "Content-Type": "application/json"}
    status, body, _ = prowlarr("GET", "/api/v1/indexer", key)
    mam = next((i for i in json.loads(body) if i["implementation"] == "MyAnonamouse"), None) if status == 200 else None
    if not mam or not any(f["name"] == "useFreeleechWedge" and f["value"] for f in mam["fields"]):
        return None
    prowlarr("PUT", f"/api/v1/indexer/{mam['id']}?forceSave=true", key, json.dumps(with_wedge(mam, False)).encode())
    try:
        result = prowlarr("POST", "/api/v1/search", headers, data)
    finally:
        prowlarr("PUT", f"/api/v1/indexer/{mam['id']}?forceSave=true", key, json.dumps(mam).encode())
    log.warning("grab with wedge failed, retried without: HTTP %s", result[0])
    return result


QBIT = None


def torrent_file():
    """The .torrent ABR wants for its hash: the abr torrent qBittorrent got in the last 3 minutes, never a new MAM download."""
    fresh = [t for t in QBIT.category() if time.time() - t["added_on"] < 180]
    if not fresh:
        return 404, b"not found", "text/plain"
    h = max(fresh, key=lambda t: t["added_on"])["hash"]
    with QBIT.opener.open(f"{QBIT_URL}/api/v2/torrents/export?hash={h}", timeout=30) as r:
        return 200, r.read(), "application/x-bittorrent"


def forward(handler, method):
    """Pass-through to Prowlarr; search results get the release policy (ranking.py)."""
    path = handler.path[len("/prowlarr"):]
    length = int(handler.headers.get("Content-Length", 0))
    data = handler.rfile.read(length) if length else None
    headers = {k: v for k, v in handler.headers.items() if k.lower() in ("x-api-key", "content-type", "accept", "user-agent")}
    url = urllib.parse.urlsplit(path)
    if method == "GET" and url.path == "/torrent":
        status, body, ctype = torrent_file()
    else:
        status, body, ctype = prowlarr(method, path, headers, data)
        if method == "POST" and url.path == "/api/v1/search" and status >= 400:
            status, body, ctype = grab_without_wedge(headers, data) or (status, body, ctype)
    if method == "GET" and url.path == "/api/v1/search" and status == 200:
        query = urllib.parse.parse_qs(url.query).get("query", [""])[0]
        prefs = REQUESTS.prefs(query)
        results = json.loads(body)
        ranked = for_abr(results, prefs, proxy_base=PROXY_BASE)
        log.info("search %r: %d -> %d results (%s, unabridged=%s)", query, len(results), len(ranked), prefs.language, prefs.unabridged)
        body = json.dumps(ranked).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def all_requests_handler(handler):
    try:
        auth = {"Authorization": f"Bearer {REQUESTS.key}"}
        with lock:
            jobs = load()
        body = json.dumps(all_requests(http_json(f"{ABR_URL}/api/requests", headers=auth) or [],
                                       http_json(f"{ABR_URL}/api/requests/manual", headers=auth) or [], jobs)).encode()
        status = 200
    except (urllib.error.URLError, ValueError) as e:
        log.error("all-requests: %s", e)
        status, body = 502, b"[]"
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


quota_lock = threading.Lock()


def load_ledger():
    try:
        return json.loads(QUOTA_LEDGER.read_text())
    except FileNotFoundError:
        return {}


def snapshot_quota():
    """Adds ABR's live requests to the ledger; returns (wishlist, manual, ledger)."""
    auth = {"Authorization": f"Bearer {REQUESTS.key}"}
    wishlist = http_json(f"{ABR_URL}/api/requests", headers=auth) or []
    manual = http_json(f"{ABR_URL}/api/requests/manual", headers=auth) or []
    with quota_lock:
        ledger = merge_ledger(load_ledger(), quota_entries(wishlist, manual), time.time())
        tmp = QUOTA_LEDGER.with_suffix(".tmp")
        tmp.write_text(json.dumps(ledger))
        tmp.replace(QUOTA_LEDGER)
    return wishlist, manual, ledger


def quota(handler):
    """nginx auth_request for ABR's request endpoints: 204 = allowed, 403 = limit reached."""
    user = handler.headers.get("X-authentik-username", "")
    ok = handler.headers.get("X-Original-Method", "POST") != "POST"
    if not ok:
        try:
            wishlist, manual, ledger = snapshot_quota()
            ok = quota_ok(wishlist, manual, user, time.time(), ledger)
        except (urllib.error.URLError, ValueError, OSError) as e:
            log.error("quota check for %s: %s", user, e)
            ok = False
        if not ok:
            log.info("quota: %s refused (%d per %d days)", user, QUOTA_BOOKS, QUOTA_DAYS)
    handler.send_response(204 if ok else 403)
    handler.end_headers()


def abs_forward(handler):
    """ABR's Audiobookshelf base URL. Its "already in library" search covers one library; ABS has one per language,
    so a search is asked in every book library. Everything else passes through with ABR's own (read-only) key."""
    path = handler.path[len("/abs"):]
    auth = {"Authorization": handler.headers.get("Authorization", "")}
    url = urllib.parse.urlsplit(path)
    try:
        if re.fullmatch(r"/api/libraries/[^/]+/search", url.path):
            libs = http_json(f"{ABS_URL}/api/libraries", headers=auth)["libraries"]
            body = json.dumps(merge_searches(
                [http_json(f"{ABS_URL}/api/libraries/{i}/search?{url.query}", headers=auth) or {}
                 for i in book_library_ids(libs)])).encode()
            status = 200
        else:
            with urllib.request.urlopen(urllib.request.Request(ABS_URL + path, headers=auth), timeout=30) as r:
                status, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, body = e.code, b"{}"
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not caller_ok(self.path, self.client_address[0]):
            return self.send_error(403)
        if self.path.startswith("/prowlarr/"):
            return forward(self, "GET")
        if self.path.startswith("/abs/"):
            return abs_forward(self)
        if self.path == "/all-requests":
            return all_requests_handler(self)
        if self.path == "/quota":
            return quota(self)
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path.startswith("/prowlarr/"):
            return forward(self, "POST")
        if self.path != "/abr":
            return self.send_error(404)
        try:
            length = int(self.headers.get("Content-Length", 0))
            job = parse_webhook(json.loads(self.rfile.read(min(length, 65536))))
        except (ValueError, json.JSONDecodeError) as e:
            return self.send_error(400, str(e))
        with lock:
            jobs = load()
            key = job["hash"] or f"unbound-{job['added']:.0f}"
            if key not in jobs:
                jobs[key] = job
                save(jobs)
        log.info("queued %s %s", (job["hash"] or "unbound")[:8], job["title"])
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


def secret(path):
    try:
        return Path(path).read_text().strip() if path else ""
    except FileNotFoundError:
        return ""


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    global QBIT
    qbit = QBIT = Qbit(secret(ENV("QBIT_PASS_FILE")))
    abs_ = Abs(ENV("ABS_KEY_FILE"))
    REQUESTS.key = secret(ENV("ABR_KEY_FILE"))
    threading.Thread(target=poll, args=(qbit, abs_), daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", int(ENV("PORT", "8000"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
