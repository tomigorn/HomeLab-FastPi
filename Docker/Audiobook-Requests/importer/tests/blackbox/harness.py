"""Starts the importer under test (IMPORTER_CMD) against the fakes in mocks.py, as a black box over HTTP.

Peers: the importer trusts callers by address. Everything runs on loopback, so the client binds its source address:
127.0.0.2 = books-proxy, 127.0.0.3 = ABR (ABR_HOST=localhost makes 127.0.0.1 ABR by name too), 127.0.0.4 = anybody else."""
import atexit
import http.client
import json
import os
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import mocks

HERE = Path(__file__).resolve().parent
IMPORTER_DIR = HERE.parent.parent
DEFAULT_CMD = f"python3 {IMPORTER_DIR / 'importer.py'}"
WORK = Path(os.environ.get("BLACKBOX_WORK", Path.home() / ".cache/claude-work/importer-blackbox"))
PEERS = {"proxy": "127.0.0.2", "abr": "127.0.0.3", "other": "127.0.0.4", "abr-by-name": "127.0.0.1"}
LEGACY = os.environ.get("IMPORTER_LEGACY") == "1"
AUDIBLE_MOCK = os.environ.get("AUDIBLE_MOCK") == "1"
STARTUPS = []
atexit.register(lambda: STARTUPS and print(f"startup to /health: median {sorted(STARTUPS)[len(STARTUPS) // 2] * 1000:.0f} ms over {len(STARTUPS)} starts"))


def legacy_bug(reason):
    """The current Python has this bug; the test documents the correct behaviour and runs on the rewrite only."""
    return unittest.skipIf(LEGACY, f"legacy bug: {reason}")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Service:
    def __init__(self, env=None, abs_key="abs-importer-key", abr_key="abr-importer-key"):
        WORK.mkdir(parents=True, exist_ok=True)
        self.tmp = Path(tempfile.mkdtemp(prefix="bb-", dir=WORK))
        self.library = self.tmp / "library"
        self.downloads = self.tmp / "downloads"
        self.data = self.tmp / "data"
        secrets = self.tmp / "secrets"
        for d in (self.library, self.downloads, self.data, secrets):
            d.mkdir()
        self.qbit, self.abs, self.abr, self.prowlarr, self.audible = mocks.Qbit(), mocks.Abs(abs_key), mocks.Abr(abr_key), mocks.Prowlarr(), mocks.Audible()
        (secrets / "qbit_pass").write_text(self.qbit.password + "\n")
        (secrets / "abs_api_key").write_text(abs_key + "\n")
        (secrets / "abr_api_key").write_text(abr_key + "\n")
        self.port = free_port()
        self.env = {
            "PORT": str(self.port), "POLL_SECONDS": "1", "TZ": "UTC",
            "QBIT_URL": self.qbit.url, "ABS_URL": self.abs.url, "ABR_URL": self.abr.url, "PROWLARR_URL": self.prowlarr.url,
            "AUDIBLE_BASE": f"{self.audible.url}/audible", "AUDNEXUS_URL": f"{self.audible.url}/audnexus",
            "AUDIBLE_REGIONS": "com" if AUDIBLE_MOCK else "invalid",
            "LIBRARY": str(self.library), "STATE": str(self.data / "jobs.json"), "QUOTA_LEDGER": str(self.data / "quota.json"),
            "QBIT_PASS_FILE": str(secrets / "qbit_pass"), "ABS_KEY_FILE": str(secrets / "abs_api_key"), "ABR_KEY_FILE": str(secrets / "abr_api_key"),
            "BOOKS_PROXY_IP": PEERS["proxy"], "ABR_IP": PEERS["abr"], "ABR_HOST": "localhost",
            "PROXY_BASE": "http://audiobook-importer:8000/prowlarr", "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        }
        self.env.update(env or {})
        self.log = open(self.tmp / "importer.log", "wb")
        self.proc = None

    def start(self, timeout=20):
        cmd = shlex.split(os.environ.get("IMPORTER_CMD", DEFAULT_CMD))
        t0 = time.monotonic()
        self.proc = subprocess.Popen(cmd, env=self.env, cwd=self.tmp, stdout=self.log, stderr=subprocess.STDOUT)
        while time.monotonic() - t0 < timeout:
            if self.proc.poll() is not None:
                raise RuntimeError(f"importer exited {self.proc.returncode}: {self.log_text()[-2000:]}")
            try:
                if self.request("GET", "/health", peer="other")[0] == 200:
                    STARTUPS.append(time.monotonic() - t0)
                    return self
            except OSError:
                pass
            time.sleep(0.02)
        raise RuntimeError(f"importer did not come up: {self.log_text()[-2000:]}")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.log.close()
        for m in (self.qbit, self.abs, self.abr, self.prowlarr, self.audible):
            m.close()
        if os.environ.get("BLACKBOX_KEEP") != "1":
            shutil.rmtree(self.tmp, ignore_errors=True)

    def log_text(self):
        self.log.flush()
        return (self.tmp / "importer.log").read_text(errors="replace")

    def request(self, method, path, peer="proxy", body=None, headers=None, timeout=15):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout, source_address=(PEERS[peer], 0))
        try:
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            c.request(method, path, body=body, headers=headers or {})
            r = c.getresponse()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
        finally:
            c.close()

    def json(self, method, path, **kw):
        status, headers, body = self.request(method, path, **kw)
        return status, headers, (json.loads(body) if body else None)

    def headers_only(self, method, path, length, peer="abr"):
        """Sends the headers of a POST and nothing else: the body limit must answer before reading."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15, source_address=(PEERS[peer], 0))
        try:
            c.putrequest(method, path)
            c.putheader("Content-Length", str(length))
            c.putheader("Content-Type", "application/json")
            c.endheaders()
            return c.getresponse().status
        finally:
            c.close()

    def jobs(self):
        p = self.data / "jobs.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def write_jobs(self, jobs):
        (self.data / "jobs.json").write_text(json.dumps(jobs, indent=1))

    def ledger(self):
        p = self.data / "quota.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def write_ledger(self, ledger):
        (self.data / "quota.json").write_text(json.dumps(ledger))

    def wait_for(self, predicate, timeout=12, what="condition"):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            try:
                value = predicate()
            except (OSError, ValueError):
                value = None
            if value:
                return value
            time.sleep(0.1)
        raise AssertionError(f"timed out waiting for {what}; jobs={self.jobs()}; log tail:\n{self.log_text()[-3000:]}")

    def wait_state(self, key_pred, state, timeout=12):
        def find():
            for k, j in self.jobs().items():
                if key_pred(k, j) and j.get("state") == state:
                    return j
        return self.wait_for(find, timeout, f"a job in state {state}")

    def reset_mocks(self):
        for m in (self.qbit, self.abs, self.abr, self.prowlarr, self.audible):
            m.reset()


class ServiceTest(unittest.TestCase):
    """One importer per test class; override env() for other settings."""
    ENV = {}
    ABS_KEY = "abs-importer-key"

    @classmethod
    def setUpClass(cls):
        cls.svc = Service(cls.ENV, abs_key=cls.ABS_KEY)
        cls.prepare(cls.svc)
        cls.svc.start()

    @classmethod
    def prepare(cls, svc):
        pass

    @classmethod
    def tearDownClass(cls):
        cls.svc.stop()

    def setUp(self):
        self.svc.reset_mocks()


def abs_user(name, type_="user", libs=(), all_libs=True, all_tags=True, tags=(), not_tags=False, explicit=True, oidc=True):
    return {"username": name, "type": type_, "isActive": True, "hasOpenIDLink": oidc, "librariesAccessible": list(libs),
            "itemTagsSelected": list(tags), "token": "SECRET-TOKEN", "email": "x@example.com",
            "permissions": {"accessAllLibraries": all_libs, "accessAllTags": all_tags, "selectedTagsNotAccessible": not_tags,
                            "accessExplicitContent": explicit}}


def abs_item(i, lib="en", asin=None, size=100, tags=(), explicit=False, title=None, added=1770425220177):
    return {"id": i, "libraryId": lib, "size": size, "addedAt": added, "path": "/audiobooks/EN/x", "relPath": "x", "ino": "1",
            "media": {"duration": 3600.5, "tags": list(tags), "numAudioFiles": 1,
                      "metadata": {"title": title or "T" + i, "subtitle": "Sub", "authorName": "Jane Doe", "narratorName": "John Roe",
                                   "seriesName": "Saga #1", "asin": asin, "explicit": explicit, "language": "English",
                                   "description": "long text", "publishedYear": "2010"}}}


def wish(asin, title, user, at, authors=("Jane Doe", "X"), narrators=(), downloaded=False, cover=True):
    return {"book": {"asin": asin, "title": title, "authors": list(authors), "narrators": list(narrators), "downloaded": downloaded,
                     "cover_image": f"https://img/{asin}.jpg" if cover else None},
            "requests": [{"user_username": user, "updated_at": at, "asin": asin}]}
