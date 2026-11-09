"""HTTP behaviour of the importer: who may call what, quota, pages' data, the ABS and Prowlarr pass-throughs."""
import datetime
import json
import os
import shlex
import subprocess
import time
import unittest
from zoneinfo import ZoneInfo

import harness
from harness import ServiceTest, abs_item, abs_user, legacy_bug, wish
from mocks import SENSE

HASH = "a" * 40
GATED = ("/quota", "/all-requests", "/my-quota", "/library", "/library-cover/x", "/sizes")


class Health(ServiceTest):
    def test_health_from_anyone(self):
        status, _, body = self.svc.request("GET", "/health", peer="other")
        self.assertEqual((status, body), (200, b"ok"))

    def test_unknown_paths(self):
        self.assertEqual(self.svc.request("GET", "/nope", peer="other")[0], 404)
        self.assertEqual(self.svc.request("GET", "/abr", peer="abr")[0], 404)
        self.assertEqual(self.svc.request("POST", "/nope", peer="abr", body=b"{}")[0], 404)


class Callers(ServiceTest):
    def test_books_proxy_paths_refused_for_other_peers(self):
        for path in GATED:
            for peer in ("other", "abr"):
                self.assertEqual(self.svc.request("GET", path, peer=peer)[0], 403, (path, peer))

    def test_torrent_only_from_abr(self):
        for peer in ("other", "proxy"):
            self.assertEqual(self.svc.request("GET", "/prowlarr/torrent?guid=x", peer=peer)[0], 403)
        self.assertEqual(self.svc.request("GET", "/prowlarr/torrent?guid=x", peer="abr")[0], 404)

    def test_posts_only_from_abr(self):
        for path in ("/abr", "/prowlarr/api/v1/search"):
            for peer in ("other", "proxy"):
                self.assertEqual(self.svc.request("POST", path, peer=peer, body=b"{}")[0], 403, (path, peer))

    def test_abr_by_name_on_the_other_network(self):
        body = {"hash": HASH, "asin": "B000TEST01", "title": "T", "authors": "A"}
        self.assertEqual(self.svc.request("POST", "/abr", peer="abr-by-name", body=body)[0], 204)

    def test_abs_posts_never_pass(self):
        for peer in ("other", "abr", "proxy"):
            self.assertEqual(self.svc.request("POST", "/abs/api/libraries/x/scan", peer=peer, body=b"")[0], 404)
        self.assertEqual(self.svc.abs.calls, [])

    def test_other_prowlarr_gets_pass_for_anyone(self):
        status, _, body = self.svc.json("GET", "/prowlarr/api/v1/echo?x=1", peer="other", headers={"X-Api-Key": "k"})
        self.assertEqual((status, body["apikey"]), (200, "k"))


class BodyLimits(ServiceTest):
    def test_over_one_mb_is_refused_unread(self):
        for path in ("/abr", "/prowlarr/api/v1/search"):
            self.assertEqual(self.svc.headers_only("POST", path, 1024 * 1024 + 1), 413, path)

    def test_bad_content_length(self):
        for path in ("/abr", "/prowlarr/api/v1/search"):
            for bad in ("abc", "-5"):
                self.assertEqual(self.svc.headers_only("POST", path, bad), 400, (path, bad))

    def test_one_mb_exactly_passes_the_gate(self):
        body = b'{"hash": "%s", "pad": "%s"}' % (HASH.encode(), b"x" * 60000)
        self.assertEqual(self.svc.request("POST", "/abr", peer="abr", body=body)[0], 204)


class Webhook(ServiceTest):
    def test_valid_webhook_queues_a_pending_job(self):
        before = time.time()
        body = {"hash": HASH.upper(), "asin": "B000TEST01", "title": "The Yellow Wallpaper", "authors": "Charlotte Perkins Gilman, X Y",
                "source": "The Yellow Wallpaper by Charlotte Perkins Gilman [ENG / M4B]", "indexer": "MyAnonamouse"}
        self.assertEqual(self.svc.request("POST", "/abr", peer="abr", body=body)[0], 204)
        job = self.svc.jobs()[HASH]
        self.assertEqual(job["hash"], HASH)
        self.assertEqual(job["asin"], "B000TEST01")
        self.assertEqual(job["title"], "The Yellow Wallpaper")
        self.assertEqual(job["authors"], ["Charlotte Perkins Gilman", "X Y"])
        self.assertEqual(job["source"], body["source"])
        self.assertEqual(job["indexer"], "MyAnonamouse")
        self.assertEqual(job["state"], "pending")
        self.assertTrue(before - 1 <= job["added"] <= time.time() + 1)

    def test_duplicate_webhook_keeps_the_first(self):
        h = "b" * 40
        self.svc.request("POST", "/abr", peer="abr", body={"hash": h, "title": "first"})
        first = self.svc.jobs()[h]
        self.assertEqual(self.svc.request("POST", "/abr", peer="abr", body={"hash": h, "title": "second"})[0], 204)
        self.assertEqual(self.svc.jobs()[h], first)

    def test_bad_hash_and_bad_json(self):
        self.assertEqual(self.svc.request("POST", "/abr", peer="abr", body={"hash": "../../etc", "asin": "B000TEST01"})[0], 400)
        self.assertEqual(self.svc.request("POST", "/abr", peer="abr", body=b"not json")[0], 400)

    @legacy_bug("a JSON body that is not an object crashes the handler: the connection closes without a response")
    def test_json_that_is_not_an_object(self):
        self.assertEqual(self.svc.request("POST", "/abr", peer="abr", body=b"[1, 2]")[0], 400)
        self.assertEqual(self.svc.request("POST", "/abr", peer="abr", body=b"null")[0], 400)

    def test_placeholders_are_dropped(self):
        h = "c" * 40
        self.svc.request("POST", "/abr", peer="abr", body={"hash": h, "asin": "{bookASIN}", "title": "{bookTitle}", "authors": "", "source": "{x}"})
        job = self.svc.jobs()[h]
        self.assertIsNone(job["asin"])
        self.assertEqual((job["title"], job["authors"], job["source"]), ("", [], ""))

    def test_manual_pick_without_hash_waits_unbound(self):
        self.svc.request("POST", "/abr", peer="abr", body={"hash": "{torrentInfoHash}", "asin": "B000TEST02", "title": "Manual"})
        key, job = next((k, j) for k, j in self.svc.jobs().items() if k.startswith("unbound-"))
        self.assertEqual(key, f"unbound-{job['added']:.0f}")
        self.assertIsNone(job["hash"])
        self.assertEqual(job["state"], "unbound")


class Quota(ServiceTest):
    def setUp(self):
        super().setUp()
        self.svc.abr.wishlist, self.svc.abr.manual, self.svc.abr.fail = [], [], False
        self.svc.write_ledger({})

    def iso(self, days_ago):
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - days_ago * 86400))

    def wishes(self, user, n, days_ago=1):
        return [wish(f"B{i}", f"T{i}", user, self.iso(days_ago)) for i in range(n)]

    def quota(self, user, method="POST"):
        headers = {"X-Original-Method": method}
        if user is not None:
            headers["X-authentik-username"] = user
        return self.svc.request("GET", "/quota", peer="proxy", headers=headers)[0]

    def test_non_post_is_always_allowed_without_asking_abr(self):
        self.assertEqual(self.quota("jane", "GET"), 204)
        self.assertEqual(self.svc.abr.named("GET", "/api/requests"), [])

    def test_fifth_allowed_sixth_refused(self):
        self.svc.abr.wishlist = self.wishes("jane", 4)
        self.assertEqual(self.quota("jane"), 204)
        self.svc.abr.wishlist = self.wishes("jane", 5)
        self.assertEqual(self.quota("jane"), 403)

    def test_other_users_and_old_requests_do_not_count(self):
        self.svc.abr.wishlist = self.wishes("john", 5) + self.wishes("jane", 5, days_ago=8)
        self.assertEqual(self.quota("jane"), 204)

    def test_manual_requests_count(self):
        self.svc.abr.wishlist = self.wishes("jane", 3)
        self.svc.abr.manual = [{"id": i, "title": "M", "authors": [], "user_username": "jane", "updated_at": self.iso(2)} for i in range(2)]
        self.assertEqual(self.quota("jane"), 403)

    def test_no_user_or_abr_down_refuses(self):
        self.assertEqual(self.quota(None), 403)
        self.assertEqual(self.quota(""), 403)
        self.svc.abr.fail = True
        self.assertEqual(self.quota("jane"), 403)

    def test_deleted_requests_keep_counting_through_the_ledger(self):
        self.svc.abr.wishlist = self.wishes("jane", 5)
        self.assertEqual(self.quota("jane"), 403)
        ledger = self.svc.ledger()
        self.assertEqual(sorted(ledger), [f"jane|B{i}" for i in range(5)])
        self.assertEqual(ledger["jane|B0"]["user"], "jane")
        self.assertAlmostEqual(ledger["jane|B0"]["at"], time.time() - 86400, delta=5)
        self.svc.abr.wishlist = []
        self.assertEqual(self.quota("jane"), 403)

    def test_admins_have_the_same_limit(self):
        self.svc.abr.wishlist = self.wishes("owner", 5)
        self.assertEqual(self.quota("owner"), 403)


class MyQuota(ServiceTest):
    NOW = None

    def setUp(self):
        super().setUp()
        self.svc.abr.wishlist = []

    def ledger(self, *entries):
        now = time.time()
        return {f"{u}|B{i}": {"user": u, "at": now - d * 86400} for i, (u, d) in enumerate(entries)}

    def test_no_user_is_a_400_null(self):
        status, headers, body = self.svc.request("GET", "/my-quota", peer="proxy")
        self.assertEqual((status, body), (400, b"null"))
        self.assertEqual(headers.get("content-type"), "application/json")

    def test_own_count_only(self):
        self.svc.write_ledger(self.ledger(("jane", 1), ("jane", 2), ("john", 1), ("jane", 8)))
        status, headers, q = self.svc.json("GET", "/my-quota", peer="proxy", headers={"X-authentik-username": "jane"})
        self.assertEqual((status, q), (200, {"used": 2, "limit": 5, "days": 7, "freesAt": None}))
        self.assertEqual(headers.get("cache-control"), "no-store")

    def test_full_says_when_the_oldest_slot_frees(self):
        ledger = self.ledger(*[("jane", d) for d in (1, 2, 3, 4, 6.5)])
        self.svc.write_ledger(ledger)
        _, _, q = self.svc.json("GET", "/my-quota", peer="proxy", headers={"X-authentik-username": "jane"})
        oldest = min(v["at"] for v in ledger.values())
        self.assertEqual(q["used"], 5)
        self.assertEqual(q["freesAt"], time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(oldest + 7 * 86400)))


ZURICH = ZoneInfo("Europe/Zurich")


class QuotaLocalTime(ServiceTest):
    """ABR writes updated_at with datetime.now() in its container (TZ=Europe/Zurich): naive times are local time, read in the importer's TZ."""
    ENV = {"TZ": "Europe/Zurich"}

    def setUp(self):
        super().setUp()
        self.svc.abr.wishlist, self.svc.abr.manual, self.svc.abr.fail = [], [], False
        self.svc.write_ledger({})

    def local(self, seconds_ago):
        return datetime.datetime.fromtimestamp(time.time() - seconds_ago, ZURICH).strftime("%Y-%m-%dT%H:%M:%S")

    def quota(self, user):
        return self.svc.request("GET", "/quota", peer="proxy", headers={"X-Original-Method": "POST", "X-authentik-username": user})[0]

    def test_naive_times_are_local(self):
        self.svc.abr.wishlist = [wish("B0", "T0", "jane", self.local(86400))]
        self.assertEqual(self.quota("jane"), 204)
        self.assertAlmostEqual(self.svc.ledger()["jane|B0"]["at"], time.time() - 86400, delta=5)

    def test_window_edge_is_measured_in_local_time(self):
        self.svc.abr.wishlist = [wish(f"B{i}", f"T{i}", "jane", self.local(7 * 86400 - 1200)) for i in range(5)]
        self.assertEqual(self.quota("jane"), 403)
        self.svc.write_ledger({})
        self.svc.abr.wishlist = [wish(f"B{i}", f"T{i}", "jane", self.local(7 * 86400 + 1200)) for i in range(5)]
        self.assertEqual(self.quota("jane"), 204)

    def test_log_lines_are_stamped_in_local_time(self):
        self.quota("")
        first = self.svc.wait_for(lambda: next((l for l in self.svc.log_text().splitlines() if "refused" in l), None), what="a log line")
        stamped = datetime.datetime.strptime(first[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZURICH)
        self.assertLess(abs(time.time() - stamped.timestamp()), 300, first)


class QuotaLocalTimeFixedDates(ServiceTest):
    """Fixed dates around a week boundary and both DST switches (values from the Python's datetime.fromisoformat(...).timestamp())."""
    ENV = {"TZ": "Europe/Zurich", "QUOTA_DAYS": "36500"}
    EXPECTED = {
        "2026-11-08T23:30:00": 1794177000.0,   # Sunday 23:30 CET
        "2026-11-09T00:30:00": 1794180600.0,   # Monday 00:30 CET
        "2026-01-01T00:00:00": 1767222000.0,
        "2026-07-01T00:00:00": 1782856800.0,
        "2026-03-29T01:30:00": 1774744200.0,   # before the spring switch (CET)
        "2026-03-29T02:30:00": 1774747800.0,   # does not exist: read with the offset before the switch
        "2026-03-29T03:30:00": 1774747800.0,   # CEST
        "2026-10-25T01:30:00": 1792884600.0,
        "2026-10-25T02:30:00": 1792888200.0,   # twice: the first (CEST)
        "2026-10-25T03:30:00": 1792895400.0,
        "2026-07-01T12:00:00.250000": 1782900000.25,
        "2026-07-01 12:00:00": 1782900000.0,
        "2026-07-01T12:00:00+00:00": 1782907200.0,
        "2026-07-01T12:00:00Z": 1782907200.0,
        "2026-01-01": 1767222000.0,
    }

    def test_ledger_times(self):
        self.svc.abr.wishlist = [wish(f"B{i}", "T", "jane", at) for i, at in enumerate(self.EXPECTED)]
        self.svc.abr.manual, self.svc.abr.fail = [], False
        self.svc.write_ledger({})
        self.svc.request("GET", "/quota", peer="proxy", headers={"X-Original-Method": "POST", "X-authentik-username": "jane"})
        ledger = self.svc.ledger()
        got = {at: ledger[f"jane|B{i}"]["at"] for i, at in enumerate(self.EXPECTED)}
        self.assertEqual(got, self.EXPECTED)


@unittest.skipIf(harness.LEGACY, "the Python has python3 in its image instead of a probe")
class Probe(ServiceTest):
    """--probe <http url>: the status line's code on stdout, for checks that run inside the shell-less image (docker exec)."""

    def probe(self, url):
        cmd = shlex.split(os.environ["IMPORTER_CMD"]) + ["--probe", url]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return r.returncode, r.stdout.strip()

    def test_status_code_of_any_answer(self):
        self.assertEqual(self.probe(f"http://127.0.0.1:{self.svc.port}/health"), (0, "200"))
        self.assertEqual(self.probe(f"http://127.0.0.1:{self.svc.port}/quota"), (0, "403"))

    def test_nothing_listening_or_not_http(self):
        self.assertEqual(self.probe(f"http://127.0.0.1:{harness.free_port()}/")[0], 1)
        self.assertEqual(self.probe("https://127.0.0.1/")[0], 2)
        self.assertEqual(self.probe("http://example.com/")[0], 2)


class AllRequests(ServiceTest):
    NOW_JOB = {"hash": "h2" * 20, "asin": "A2", "title": "T", "authors": [], "source": "", "indexer": "", "state": "pending", "added": 0}

    @classmethod
    def prepare(cls, svc):
        svc.write_jobs({cls.NOW_JOB["hash"]: cls.NOW_JOB, "h3" * 20: dict(cls.NOW_JOB, hash="h3" * 20, asin="A3", state="done")})
        svc.abs.users = [abs_user("jane")]
        svc.abs.items = {"en": [abs_item("1", asin="A3", size=4321)]}
        svc.qbit.torrents = [{"hash": "h2" * 20, "category": "abr", "progress": 0.2, "added_on": int(time.time()), "size": 555,
                              "content_path": str(svc.downloads / "x")}]

    def setUp(self):
        super().setUp()
        self.svc.abr.fail = False
        self.svc.abr.wishlist = [wish("A1", "TA1", "jane", "2026-10-20T10:00:00"),
                                 dict(wish("A2", "TA2", "john", "2026-10-25T10:00:00", downloaded=True),
                                      requests=[{"user_username": "john", "updated_at": "2026-10-25T10:00:00"},
                                                {"user_username": "jane", "updated_at": "2026-10-26T09:00:00"}]),
                                 wish("A3", "TA3", "jane", "2026-10-24T10:00:00", downloaded=True)]
        self.svc.abr.manual = [{"id": 7, "title": "M", "authors": ["A"], "user_username": "jane", "updated_at": "2026-10-22T10:00:00", "downloaded": False}]

    def test_everyones_requests_newest_first_with_status_and_sizes(self):
        status, headers, rows = self.svc.json("GET", "/all-requests", peer="proxy", headers={"X-authentik-username": "jane"})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertEqual([(r["title"], r["requested_by"], r["status"]) for r in rows],
                         [("TA2", "jane", "downloading"), ("TA2", "john", "downloading"), ("TA3", "jane", "in library"),
                          ("M", "jane", "open"), ("TA1", "jane", "open")])
        self.assertEqual(rows[0], {"title": "TA2", "author": "Jane Doe, X", "cover": "https://img/A2.jpg", "asin": "A2", "size": 555,
                                   "requested_by": "jane", "requested": "2026-10-26T09:00:00", "status": "downloading"})
        self.assertEqual(rows[2]["size"], 4321)
        self.assertEqual(rows[3], {"title": "M", "author": "A", "cover": None, "asin": None, "size": None, "requested_by": "jane",
                                   "requested": "2026-10-22T10:00:00", "status": "open"})
        self.assertIsNone(rows[4]["size"])

    def test_sizes_follow_the_viewers_abs_account(self):
        _, _, rows = self.svc.json("GET", "/all-requests", peer="proxy", headers={"X-authentik-username": "nobody"})
        self.assertEqual({r["asin"]: r["size"] for r in rows if r["asin"]}, {"A1": None, "A2": 555, "A3": None})

    def test_abr_down_is_a_502_with_an_empty_list(self):
        self.svc.abr.fail = True
        status, _, body = self.svc.request("GET", "/all-requests", peer="proxy", headers={"X-authentik-username": "jane"})
        self.assertEqual((status, body), (502, b"[]"))


class Library(ServiceTest):
    @classmethod
    def prepare(cls, svc):
        svc.abs.users = [abs_user("jane", explicit=False), abs_user("root", "root"), abs_user("local", oidc=False),
                         abs_user("kids", all_tags=False, tags=["kids"]), abs_user("off")]
        svc.abs.users[-1]["isActive"] = False
        svc.abs.items = {"en": [abs_item("1", asin="A1"), abs_item("2", tags=["kids"]), abs_item("3", explicit=True)],
                         "de": [abs_item("4", lib="de", size=300)], "pod": [abs_item("9", lib="pod")]}

    def listing(self, user):
        return self.svc.json("GET", "/library", peer="proxy", headers={"X-authentik-username": user} if user is not None else {})

    def test_unknown_viewer(self):
        status, headers, out = self.listing("post-update-nobody")
        self.assertEqual((status, out), (200, {"count": 0, "items": [], "noAbsUser": True, "abs": "https://audiobookshelf.holy-grail.ch/item/"}))
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertEqual(self.listing(None)[2]["noAbsUser"], True)

    def test_viewer_sees_only_what_abs_allows(self):
        status, _, out = self.listing("jane")
        self.assertEqual(status, 200)
        self.assertEqual((out["count"], out["noAbsUser"]), (3, False))
        self.assertEqual([r["id"] for r in out["items"]], ["1", "2", "4"])
        self.assertEqual(out["items"][0], {"id": "1", "title": "T1", "subtitle": "Sub", "author": "Jane Doe", "narrator": "John Roe",
                                           "series": "Saga #1", "duration": 3600, "size": 100, "added": "2026-02-07T00:47:00Z",
                                           "library": "[EN] Audiobooks", "asin": "A1", "year": "2010"})
        self.assertEqual(out["items"][2]["library"], "[DE] Hörbücher")
        text = json.dumps(out)
        for leak in ("SECRET-TOKEN", "example.com", "/audiobooks/EN", "long text", "relPath"):
            self.assertNotIn(leak, text)

    def test_tag_rules(self):
        self.assertEqual([r["id"] for r in self.listing("kids")[2]["items"]], ["2"])

    def test_root_local_and_inactive_accounts_are_not_viewers(self):
        for name in ("root", "local", "off", "JANE"):
            self.assertEqual(self.listing(name)[2]["noAbsUser"], True, name)

    def test_abs_is_read_with_the_importers_key_only(self):
        self.listing("jane")
        self.assertTrue(all(c.method == "GET" for c in self.svc.abs.calls))
        for c in self.svc.abs.calls:
            self.assertEqual(c.headers.get("authorization"), "Bearer abs-importer-key")


class LibraryAbsDown(ServiceTest):
    ENV = {"ABS_URL": "http://127.0.0.1:1"}

    def test_library_and_sizes_say_502(self):
        status, _, out = self.svc.json("GET", "/library", peer="proxy", headers={"X-authentik-username": "jane"})
        self.assertEqual((status, out), (502, {"error": "Audiobookshelf not reachable"}))
        status, _, out = self.svc.json("GET", "/sizes", peer="proxy", headers={"X-authentik-username": "jane"})
        self.assertEqual((status, out), (502, {}))
        self.assertEqual(self.svc.request("GET", "/library-cover/1", peer="proxy", headers={"X-authentik-username": "jane"})[0], 404)

    def test_abs_pass_through_says_502(self):
        for path in ("/abs/api/libraries", "/abs/api/libraries/x/search?q=a"):
            status, _, body = self.svc.request("GET", path, peer="other", headers={"Authorization": "Bearer abr-readonly-key"})
            self.assertEqual((status, body), (502, b"{}"), path)


class Cover(ServiceTest):
    @classmethod
    def prepare(cls, svc):
        svc.abs.users = [abs_user("jane", explicit=False)]
        svc.abs.items = {"en": [abs_item("li_1", asin="A1"), abs_item("li_3", explicit=True)]}

    def cover(self, item, user="jane"):
        return self.svc.request("GET", f"/library-cover/{item}", peer="proxy", headers={"X-authentik-username": user})

    def test_visible_cover(self):
        status, headers, body = self.cover("li_1")
        self.assertEqual((status, body), (200, self.svc.abs.cover))
        self.assertEqual(headers.get("content-type"), "image/webp")
        self.assertEqual(headers.get("cache-control"), "private, max-age=86400")
        call = self.svc.abs.named("GET", "/api/items/li_1/cover")[0]
        self.assertEqual((call.query.get("width"), call.query.get("format")), (["240"], ["webp"]))

    def test_hidden_bad_or_foreign(self):
        self.assertEqual(self.cover("li_3")[0], 404)
        self.assertEqual(self.cover("li_1", user="nobody")[0], 404)
        for bad in ("../x", "a?b=c", "a/b", "x" * 65):
            self.assertEqual(self.cover(bad)[0], 404, bad)
        self.assertEqual(self.svc.abs.named("GET", "/api/items/li_3/cover"), [])

    def test_abs_cover_error_is_a_404(self):
        self.svc.abs.cover_status = 500
        try:
            self.assertEqual(self.cover("li_1")[0], 404)
        finally:
            self.svc.abs.cover_status = 200


class Sizes(ServiceTest):
    @classmethod
    def prepare(cls, svc):
        svc.abs.users = [abs_user("jane", explicit=False)]
        svc.abs.items = {"en": [abs_item("1", asin="A1"), abs_item("3", asin="A3", explicit=True, size=333)]}
        now = int(time.time())
        svc.write_jobs({"h3" * 20: {"hash": "h3" * 20, "asin": "A3", "state": "pending", "added": now},
                        "h9" * 20: {"hash": "h9" * 20, "asin": "A9", "state": "pending", "added": now},
                        "h8" * 20: {"hash": "h8" * 20, "asin": "A8", "state": "failed", "added": now}})
        svc.qbit.torrents = [{"hash": "h3" * 20, "category": "abr", "progress": 0.1, "added_on": now, "size": 777, "content_path": "/x"},
                             {"hash": "h9" * 20, "category": "abr", "progress": 0.1, "added_on": now, "size": 555, "content_path": "/x"},
                             {"hash": "h8" * 20, "category": "abr", "progress": 0.1, "added_on": now, "size": 111, "content_path": "/x"}]

    def test_abs_sizes_for_visible_books_and_torrent_sizes_while_downloading(self):
        status, _, out = self.svc.json("GET", "/sizes", peer="proxy", headers={"X-authentik-username": "jane"})
        self.assertEqual((status, out), (200, {"A1": 100, "A9": 555}))

    def test_unknown_viewer_gets_only_downloads(self):
        status, _, out = self.svc.json("GET", "/sizes", peer="proxy", headers={"X-authentik-username": "nobody"})
        self.assertEqual((status, out), (200, {"A9": 555}))


class AbsPassThrough(ServiceTest):
    @classmethod
    def prepare(cls, svc):
        svc.abs.search = {"en": {"book": [{"libraryItem": {"id": "1"}}], "series": [{"x": 1}], "authors": []},
                          "de": {"book": [{"libraryItem": {"id": "2"}}]}, "pod": {"book": [{"libraryItem": {"id": "p"}}]}}

    AUTH = {"Authorization": "Bearer abr-readonly-key"}

    def test_get_passes_through_with_the_callers_key(self):
        status, headers, out = self.svc.json("GET", "/abs/api/libraries", peer="other", headers=self.AUTH)
        self.assertEqual((status, out), (200, {"libraries": self.svc.abs.libraries}))
        self.assertEqual(headers.get("content-type"), "application/json")
        self.assertEqual(self.svc.abs.calls[0].headers.get("authorization"), "Bearer abr-readonly-key")

    def test_search_asks_every_book_library(self):
        status, _, out = self.svc.json("GET", "/abs/api/libraries/en/search?q=Sense%20and&limit=5", peer="other", headers=self.AUTH)
        self.assertEqual((status, out), (200, {"book": [{"libraryItem": {"id": "1"}}, {"libraryItem": {"id": "2"}}]}))
        searched = [c for c in self.svc.abs.calls if c.route.endswith("/search")]
        self.assertEqual(sorted(c.route for c in searched), ["/api/libraries/de/search", "/api/libraries/en/search", "/api/libraries/other/search"])
        self.assertTrue(all(c.query == {"q": ["Sense and"], "limit": ["5"]} for c in searched))
        self.assertTrue(all(c.headers.get("authorization") == "Bearer abr-readonly-key" for c in self.svc.abs.calls))

    def test_abs_errors_keep_their_status(self):
        status, _, body = self.svc.request("GET", "/abs/api/libraries", peer="other", headers={"Authorization": "Bearer wrong"})
        self.assertEqual((status, body), (401, b"{}"))
        status, _, body = self.svc.request("GET", "/abs/api/items/missing", peer="other", headers=self.AUTH)
        self.assertEqual((status, body), (404, b"{}"))


class ProwlarrPassThrough(ServiceTest):
    @classmethod
    def prepare(cls, svc):
        svc.abr.wishlist = [wish(None, "Sense and Sensibility", "jane", "2026-10-20T10:00:00", authors=("Jane Austen",), narrators=("Karen Savage",)),
                            wish(None, "Lonely", "jane", "2026-10-20T10:00:00", authors=("Nobody Here",))]

    def search(self, query, peer="other"):
        return self.svc.json("GET", f"/prowlarr/api/v1/search?query={query}&type=search&limit=100&categories=3030", peer=peer,
                             headers={"X-Api-Key": "pk", "Accept": "application/json"})

    def test_plain_get_passes_headers_status_and_body(self):
        status, headers, out = self.svc.json("GET", "/prowlarr/api/v1/echo?x=1&y=2", peer="other",
                                             headers={"X-Api-Key": "pk", "Accept": "application/json", "X-Other": "dropped"})
        self.assertEqual((status, out), (200, {"apikey": "pk", "path": "/api/v1/echo?x=1&y=2", "accept": "application/json"}))
        self.assertEqual(headers.get("content-type"), "application/json")
        status, headers, body = self.svc.request("GET", "/prowlarr/api/v1/unauthorized", peer="other")
        self.assertEqual((status, body, headers.get("content-type")), (401, b"Unauthorized", "text/plain"))

    def test_search_hands_abr_only_the_winner_with_the_narrator_first(self):
        status, _, out = self.search("Sense+and+Sensibility")
        self.assertEqual(status, 200)
        self.assertEqual([r["guid"] for r in out], ["https://www.myanonamouse.net/t/1039841"])
        self.assertTrue(out[0]["downloadUrl"].startswith("http://audiobook-importer:8000/prowlarr/torrent?guid=https%3A%2F%2Fwww.myanonamouse.net%2Ft%2F1039841"))
        self.assertIn("abr-newest-3", out[0]["indexerFlags"])
        queries = [c.query["query"][0] for c in self.svc.prowlarr.named("GET", "/api/v1/search")]
        self.assertEqual(queries, ["Sense and Sensibility", "Sense and Sensibility Karen Savage"])
        self.assertTrue(all(c.headers.get("x-api-key") == "pk" for c in self.svc.prowlarr.calls))
        self.assertEqual(self.svc.abr.calls[0].headers.get("authorization"), "Bearer abr-importer-key")

    def test_no_release_by_the_author_means_nothing(self):
        status, _, out = self.search("Lonely")
        self.assertEqual((status, out), (200, []))
        line = self.svc.wait_for(lambda: next((l for l in self.svc.log_text().splitlines() if "no release by Nobody Here" in l), None), what="the warning")
        self.assertEqual(line.split()[2], "WARNING", line)

    def test_unknown_book_keeps_language_and_seeder_rules(self):
        self.svc.prowlarr.results = lambda q: [dict(SENSE[0], title="X by Y [GER / M4B]"), dict(SENSE[1], seeders=0),
                                              dict(SENSE[2], title="X by Y [ENG / MP3]", guid="win")]
        try:
            status, _, out = self.search("Unknown+Book")
        finally:
            self.svc.prowlarr.results = lambda q: SENSE
        self.assertEqual((status, [r["guid"] for r in out]), (200, ["win"]))

    def test_search_error_passes_through(self):
        self.svc.prowlarr.search_status = 500
        try:
            status, _, body = self.svc.request("GET", "/prowlarr/api/v1/search?query=Sense+and+Sensibility&type=search", peer="other")
        finally:
            self.svc.prowlarr.search_status = 200
        self.assertEqual((status, body), (500, b"search failed"))


class Grab(ServiceTest):
    BODY = {"guid": "https://www.myanonamouse.net/t/1039841", "indexerId": 1}
    HEADERS = {"X-Api-Key": "pk", "Content-Type": "application/json"}

    def setUp(self):
        super().setUp()
        self.svc.prowlarr.grab_statuses = []
        self.svc.prowlarr.indexers[0]["fields"][0]["value"] = True

    def grab(self):
        return self.svc.json("POST", "/prowlarr/api/v1/search", peer="abr", body=self.BODY, headers=self.HEADERS)

    def test_grab_passes_through(self):
        status, _, out = self.grab()
        self.assertEqual((status, out), (200, {"grabbed": self.BODY}))
        self.assertEqual([c.method for c in self.svc.prowlarr.calls], ["POST"])

    def test_failed_wedge_grab_retries_once_without_the_wedge_and_restores_it(self):
        self.svc.prowlarr.grab_statuses = [400]
        status, _, out = self.grab()
        self.assertEqual((status, out), (200, {"grabbed": self.BODY}))
        self.assertEqual([(c.method, c.route) for c in self.svc.prowlarr.calls],
                         [("POST", "/api/v1/search"), ("GET", "/api/v1/indexer"), ("PUT", "/api/v1/indexer/1"),
                          ("POST", "/api/v1/search"), ("PUT", "/api/v1/indexer/1")])
        puts = self.svc.prowlarr.named("PUT", "/api/v1/indexer/1")
        self.assertEqual([p.query for p in puts], [{"forceSave": ["true"]}] * 2)
        self.assertEqual([next(f["value"] for f in p.json()["fields"] if f["name"] == "useFreeleechWedge") for p in puts], [False, True])
        self.assertEqual([p.json()["fields"][1] for p in puts], [{"name": "mamId", "value": "secret"}] * 2)
        self.assertTrue(all(c.headers.get("x-api-key") == "pk" for c in self.svc.prowlarr.calls))
        self.assertTrue(self.svc.prowlarr.wedge())

    def test_wedge_is_restored_even_when_the_retry_fails(self):
        self.svc.prowlarr.grab_statuses = [400, 503]
        status, _, out = self.grab()
        self.assertEqual((status, out), (503, {"message": "grab failed"}))
        self.assertTrue(self.svc.prowlarr.wedge())
        self.assertEqual(len(self.svc.prowlarr.named("PUT", "/api/v1/indexer/1")), 2)

    def test_no_retry_when_the_wedge_is_already_off(self):
        self.svc.prowlarr.indexers[0]["fields"][0]["value"] = False
        self.svc.prowlarr.grab_statuses = [400]
        status, _, out = self.grab()
        self.assertEqual((status, out), (400, {"message": "grab failed"}))
        self.assertEqual([c.method for c in self.svc.prowlarr.calls], ["POST", "GET"])


class TorrentFile(ServiceTest):
    def test_the_newest_fresh_abr_torrent_is_exported(self):
        now = int(time.time())
        self.svc.qbit.torrents = [{"hash": "1" * 40, "category": "abr", "added_on": now - 100, "progress": 0, "size": 1, "content_path": "/x"},
                                  {"hash": "2" * 40, "category": "abr", "added_on": now - 20, "progress": 0, "size": 1, "content_path": "/x"},
                                  {"hash": "3" * 40, "category": "other", "added_on": now - 1, "progress": 0, "size": 1, "content_path": "/x"}]
        status, headers, body = self.svc.request("GET", "/prowlarr/torrent?guid=x", peer="abr")
        self.assertEqual((status, body, headers.get("content-type")), (200, self.svc.qbit.export_bytes, "application/x-bittorrent"))
        self.assertEqual(self.svc.qbit.named("GET", "/api/v2/torrents/export")[0].query, {"hash": ["2" * 40]})

    def test_nothing_fresh_is_a_404_never_a_mam_download(self):
        now = int(time.time())
        self.svc.qbit.torrents = [{"hash": "1" * 40, "category": "abr", "added_on": now - 1000, "progress": 1, "size": 1, "content_path": "/x"}]
        status, _, body = self.svc.request("GET", "/prowlarr/torrent?guid=x", peer="abr")
        self.assertEqual((status, body), (404, b"not found"))
        self.assertEqual(self.svc.prowlarr.calls, [])


if __name__ == "__main__":
    unittest.main()
