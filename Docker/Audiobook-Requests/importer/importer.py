"""Copies finished AudioBookRequest downloads (qBittorrent category abr) into the Audiobookshelf library, then scans it."""
import json
import logging
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from naming import Book, book_dir, language_folder, mam_language
from ranking import apply_policy, prefs_from_product

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
PROWLARR_URL = ENV("PROWLARR_URL", "http://10.24.25.2:9696")
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
        shutil.copytree(src, tmp, copy_function=shutil.copy2)
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
        if not self.opener:
            self.login()
        return http_json(f"{QBIT_URL}/api/v2/torrents/info?category={CATEGORY}", opener=self.opener) or []

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
                self.post(f"/api/authors/{author['id']}/match", author_match_body(author["name"], job.get("region")))
            except urllib.error.HTTPError as e:
                log.warning("ABS author match %s: HTTP %s", author["name"], e.code)
        log.info("ABS matched %s", job["dest"])
        return True

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
    if job["state"] not in ("done", "merge-wait") or job.get("matched") or not abs_.key or "book" not in job:
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


def forward(handler, method):
    """Pass-through to Prowlarr; search results get the release policy (ranking.py)."""
    path = handler.path[len("/prowlarr"):]
    length = int(handler.headers.get("Content-Length", 0))
    data = handler.rfile.read(length) if length else None
    headers = {k: v for k, v in handler.headers.items() if k.lower() in ("x-api-key", "content-type", "accept", "user-agent")}
    req = urllib.request.Request(PROWLARR_URL + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            status, body, ctype = r.status, r.read(), r.headers.get("Content-Type", "application/json")
    except urllib.error.HTTPError as e:
        status, body, ctype = e.code, e.read(), e.headers.get("Content-Type", "text/plain")
    url = urllib.parse.urlsplit(path)
    if method == "GET" and url.path == "/api/v1/search" and status == 200:
        query = urllib.parse.parse_qs(url.query).get("query", [""])[0]
        prefs = REQUESTS.prefs(query)
        results = json.loads(body)
        ranked = apply_policy(results, prefs)
        log.info("search %r: %d -> %d results (%s, unabridged=%s)", query, len(results), len(ranked), prefs.language, prefs.unabridged)
        body = json.dumps(ranked).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/prowlarr/"):
            return forward(self, "GET")
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
    qbit = Qbit(secret(ENV("QBIT_PASS_FILE")))
    abs_ = Abs(ENV("ABS_KEY_FILE"))
    REQUESTS.key = secret(ENV("ABR_KEY_FILE"))
    threading.Thread(target=poll, args=(qbit, abs_), daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", int(ENV("PORT", "8000"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
