"""Run: python3 -m unittest discover -s Docker/Audiobook-Requests/importer"""
import tempfile
import unittest
from pathlib import Path

import importer
from naming import Book

HASH = "a" * 40


class ParseWebhookTest(unittest.TestCase):
    def test_valid_body(self):
        job = importer.parse_webhook({"hash": HASH.upper(), "asin": "B00ABC1234", "title": "T", "authors": "A B,C D",
                                      "source": "T by A B [ENG / M4B]", "indexer": "MyAnonamouse"})
        self.assertEqual(job["hash"], HASH)
        self.assertEqual(job["authors"], ["A B", "C D"])
        self.assertEqual(job["state"], "pending")

    def test_rejects_a_bad_hash(self):
        with self.assertRaises(ValueError):
            importer.parse_webhook({"hash": "../../etc", "asin": "B00ABC1234"})

    def test_unfilled_placeholders_are_dropped(self):
        job = importer.parse_webhook({"hash": HASH, "asin": "{bookASIN}", "title": "{bookTitle}", "authors": "", "source": ""})
        self.assertIsNone(job["asin"])
        self.assertEqual(job["title"], "")

    def test_manual_source_pick_has_no_hash_and_waits_for_binding(self):
        job = importer.parse_webhook({"hash": "{torrentInfoHash}", "asin": "B00ABC1234", "title": "T"})
        self.assertIsNone(job["hash"])
        self.assertEqual(job["state"], "unbound")


class BindTest(unittest.TestCase):
    def test_binds_the_closest_new_abr_torrent(self):
        job = {"added": 1000.0}
        torrents = [{"hash": "a" * 40, "added_on": 900, "category": "abr"},
                    {"hash": "b" * 40, "added_on": 1003, "category": "abr"},
                    {"hash": "c" * 40, "added_on": 1001, "category": "other"},
                    {"hash": "d" * 40, "added_on": 1002, "category": "abr"}]
        self.assertEqual(importer.bind(job, torrents, known={"d" * 40}), "b" * 40)

    def test_nothing_to_bind(self):
        self.assertIsNone(importer.bind({"added": 1000.0}, [{"hash": "a" * 40, "added_on": 500, "category": "abr"}], set()))


class ResolveBookTest(unittest.TestCase):
    job = {"title": "Webhook Title", "authors": ["Hook Author"], "source": "X by Y [GER / MP3]"}

    def test_audible_wins_and_brings_the_series(self):
        product = {"title": "The Final Empire", "authors": [{"name": "Brandon Sanderson"}],
                   "series": [{"title": "Mistborn", "sequence": "1"}], "language": "english"}
        self.assertEqual(importer.resolve_book(self.job, product),
                         Book("The Final Empire", ["Brandon Sanderson"], "Mistborn", "1", "EN"))

    def test_without_audible_the_webhook_and_mam_flags_are_used(self):
        self.assertEqual(importer.resolve_book(self.job, None), Book("Webhook Title", ["Hook Author"], None, None, "DE"))

    def test_unknown_language_is_other(self):
        job = dict(self.job, source="")
        self.assertEqual(importer.resolve_book(job, None).language, "Other")


class CopyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.lib = self.root / "lib"
        self.lib.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_folder_torrent_is_copied_and_the_source_stays(self):
        src = self.root / "dl" / "Some Torrent"
        (src / "CD1").mkdir(parents=True)
        (src / "01.mp3").write_bytes(b"1")
        (src / "CD1" / "02.mp3").write_bytes(b"2")
        dest = importer.copy_into(src, self.lib, "EN/A B/T")
        # The merger works per folder: parts in subfolders are flattened, the subfolder name keeps their order.
        self.assertEqual(sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*")), ["01.mp3", "CD1 - 02.mp3"])
        self.assertTrue((src / "01.mp3").exists())
        self.assertEqual(list(self.lib.rglob(".*")), [])

    def test_single_file_torrent(self):
        src = self.root / "book.m4b"
        src.write_bytes(b"m")
        dest = importer.copy_into(src, self.lib, "EN/A B/T")
        self.assertEqual([p.name for p in dest.iterdir()], ["book.m4b"])
        self.assertTrue(src.exists())

    def test_existing_book_is_never_overwritten(self):
        (self.lib / "EN/A B/T").mkdir(parents=True)
        (self.lib / "EN/A B/T/old.m4b").write_bytes(b"o")
        src = self.root / "book.m4b"
        src.write_bytes(b"m")
        with self.assertRaises(FileExistsError):
            importer.copy_into(src, self.lib, "EN/A B/T")
        self.assertEqual([p.name for p in (self.lib / "EN/A B/T").iterdir()], ["old.m4b"])


class MergeStateTest(unittest.TestCase):
    def test_multi_file_waits_for_the_merge(self):
        self.assertTrue(importer.needs_merge(["01.mp3", "02.mp3", "cover.jpg"]))
        self.assertFalse(importer.needs_merge(["book.m4b", "book.cue", "cover.jpg"]))
        self.assertFalse(importer.needs_merge(["one.mp3"]))

    def test_multi_part_m4b_is_merged_too(self):
        self.assertTrue(importer.needs_merge(["Part 1.m4b", "Part 2.m4b", "cover.jpg"]))


class ScanAfterMergeTest(unittest.TestCase):
    class FakeAbs:
        key = "k"

        def __init__(self):
            self.calls = []

        def scan(self, rel):
            self.calls.append(("scan", rel))

        def match(self, job):
            self.calls.append(("match", job["dest"]))
            return True

    def test_no_scan_while_the_merge_is_pending(self):
        abs_ = self.FakeAbs()
        importer.match_step({"state": "merge-wait", "dest": "EN/A/T", "book": {}, "imported": 0}, abs_, 10)
        self.assertEqual(abs_.calls, [])

    def test_scan_then_match_once_done(self):
        abs_, job = self.FakeAbs(), {"state": "done", "dest": "EN/A/T", "book": {}, "imported": 0}
        importer.match_step(job, abs_, 10)
        importer.match_step(job, abs_, 70)
        importer.match_step(job, abs_, 130)
        self.assertEqual(abs_.calls, [("scan", "EN/A/T"), ("match", "EN/A/T")])


if __name__ == "__main__":
    unittest.main()


class MatchRequestTest(unittest.TestCase):
    def test_audible_us_by_asin_overrides_details_and_cover(self):
        body = importer.match_body(Book("The Final Empire", ["Brandon Sanderson", "X"], "Mistborn", "1", "EN"), "B002UZMLXM", "com")
        self.assertEqual(body, {"provider": "audible", "asin": "B002UZMLXM", "title": "The Final Empire",
                                "author": "Brandon Sanderson", "overrideCover": True, "overrideDetails": True})

    def test_region_maps_to_the_abs_provider(self):
        self.assertEqual(importer.match_body(Book("T", ["A"]), "B000000001", "de")["provider"], "audible.de")
        self.assertEqual(importer.match_body(Book("T", ["A"]), "B000000001", "co.uk")["provider"], "audible.uk")

    def test_without_asin_it_searches_by_title_and_author(self):
        body = importer.match_body(Book("Project Hail Mary", ["Andy Weir"]), None, None)
        self.assertEqual(body["provider"], "audible")
        self.assertNotIn("asin", body)

    def test_author_match_uses_the_region(self):
        self.assertEqual(importer.author_match_body("Brandon Sanderson", "de"), {"q": "Brandon Sanderson", "region": "de"})
        self.assertEqual(importer.author_match_body("Andy Weir", None), {"q": "Andy Weir", "region": "us"})

    def test_abs_path_of_a_book(self):
        self.assertEqual(importer.abs_path("EN/A B/T"), "/audiobooks/EN/A B/T")


class LibraryForTest(unittest.TestCase):
    libs = [{"id": "en", "folders": [{"fullPath": "/audiobooks/EN"}]},
            {"id": "de", "folders": [{"fullPath": "/audiobooks/DE"}]},
            {"id": "other", "folders": [{"fullPath": "/audiobooks/Other"}]}]

    def test_one_library_per_language_folder(self):
        self.assertEqual(importer.library_for(self.libs, "DE/Jörg Müßig/T"), "de")
        self.assertEqual(importer.library_for(self.libs, "Other/A/T"), "other")

    def test_no_prefix_confusion(self):
        libs = [{"id": "x", "folders": [{"fullPath": "/audiobooks/EN"}]}]
        self.assertIsNone(importer.library_for(libs, "ENX/A/T"))


class AuthorCandidatesTest(unittest.TestCase):
    def test_other_asins_of_the_same_name_in_order_without_duplicates(self):
        found = [{"asin": "B1", "name": "Jane Doe"}, {"asin": "B1", "name": "Jane Doe"}, {"asin": "B2", "name": "Jane  Doe"},
                 {"asin": "B3", "name": "John Doe"}, {"asin": "B4", "name": "jane doe"}]
        self.assertEqual(importer.other_author_asins(found, "Jane Doe", current="B2"), ["B1", "B4"])


class QuotaTest(unittest.TestCase):
    NOW = 1_800_000_000.0

    def wish(self, *entries):
        return [{"book": {"asin": f"B{i}"}, "requests": [{"user_username": u, "updated_at": t}]} for i, (u, t) in enumerate(entries)]

    def iso(self, days_ago):
        import datetime
        return datetime.datetime.fromtimestamp(self.NOW - days_ago * 86400).isoformat()

    def test_fifth_request_allowed_sixth_refused(self):
        four = self.wish(*[("jane", self.iso(1))] * 4)
        five = self.wish(*[("jane", self.iso(1))] * 5)
        self.assertTrue(importer.quota_ok(four, [], "jane", self.NOW))
        self.assertFalse(importer.quota_ok(five, [], "jane", self.NOW))

    def test_rolling_seven_days(self):
        old = self.wish(*[("jane", self.iso(8))] * 5)
        self.assertTrue(importer.quota_ok(old, [], "jane", self.NOW))

    def test_other_users_do_not_count(self):
        self.assertTrue(importer.quota_ok(self.wish(*[("john", self.iso(1))] * 5), [], "jane", self.NOW))

    def test_manual_requests_count_too(self):
        manual = [{"user_username": "jane", "updated_at": self.iso(2)}] * 2
        self.assertFalse(importer.quota_ok(self.wish(*[("jane", self.iso(1))] * 3), manual, "jane", self.NOW))

    def test_admins_have_the_same_limit(self):
        self.assertFalse(importer.quota_ok(self.wish(*[("owner", self.iso(1))] * 5), [], "owner", self.NOW))

    def test_unknown_user_is_refused(self):
        self.assertFalse(importer.quota_ok([], [], "", self.NOW))


class QuotaLedgerTest(unittest.TestCase):
    NOW = 1_800_000_000.0

    def iso(self, days_ago):
        import datetime
        return datetime.datetime.fromtimestamp(self.NOW - days_ago * 86400).isoformat()

    def wish(self, *entries):
        return [{"book": {"asin": a}, "requests": [{"user_username": u, "updated_at": t}]} for a, u, t in entries]

    def test_a_deleted_request_still_counts(self):
        five = self.wish(*[(f"B{i}", "jane", self.iso(1)) for i in range(5)])
        ledger = importer.merge_ledger({}, importer.quota_entries(five, []), self.NOW)
        self.assertFalse(importer.quota_ok([], [], "jane", self.NOW, ledger))

    def test_live_and_ledger_entry_count_once(self):
        four = self.wish(*[(f"B{i}", "jane", self.iso(1)) for i in range(4)])
        ledger = importer.merge_ledger({}, importer.quota_entries(four, []), self.NOW)
        self.assertTrue(importer.quota_ok(four, [], "jane", self.NOW, ledger))

    def test_first_sighting_keeps_its_time(self):
        old = importer.merge_ledger({}, importer.quota_entries(self.wish(("B1", "jane", self.iso(6))), []), self.NOW)
        new = importer.merge_ledger(old, importer.quota_entries(self.wish(("B1", "jane", self.iso(0))), []), self.NOW)
        self.assertEqual(new, old)

    def test_entries_older_than_the_window_are_dropped(self):
        ledger = importer.merge_ledger({}, importer.quota_entries(self.wish(("B1", "jane", self.iso(8))), []), self.NOW)
        self.assertEqual(importer.merge_ledger(ledger, {}, self.NOW), {})

    def test_manual_requests_without_id_are_separate(self):
        manual = [{"user_username": "jane", "updated_at": self.iso(1)}] * 2
        self.assertEqual(len(importer.quota_entries([], manual)), 2)


class MyQuotaTest(unittest.TestCase):
    NOW = 1_800_000_000.0

    def ledger(self, *entries):
        return {f"{u}|B{i}": {"user": u, "at": self.NOW - d * 86400} for i, (u, d) in enumerate(entries)}

    def test_own_count_only(self):
        q = importer.my_quota(self.ledger(("jane", 1), ("jane", 2), ("john", 1)), "jane", self.NOW)
        self.assertEqual(q, {"used": 2, "limit": 5, "days": 7, "freesAt": None})

    def test_full_says_when_the_oldest_slot_frees(self):
        q = importer.my_quota(self.ledger(*[("jane", d) for d in (1, 2, 3, 4, 6.5)]), "jane", self.NOW)
        self.assertEqual((q["used"], q["freesAt"]), (5, "2027-01-15T20:00:00Z"))

    def test_outside_the_window_does_not_count(self):
        self.assertEqual(importer.my_quota(self.ledger(("jane", 8)), "jane", self.NOW)["used"], 0)

    def test_no_user_is_none(self):
        self.assertIsNone(importer.my_quota(self.ledger(("jane", 1)), "", self.NOW))


class CallerTest(unittest.TestCase):
    def test_my_quota_only_from_books_proxy(self):
        self.assertTrue(importer.caller_ok("/my-quota", "10.24.25.6"))
        self.assertFalse(importer.caller_ok("/my-quota", "10.24.25.2"))

    def test_quota_and_all_requests_only_from_books_proxy(self):
        for path in ("/quota", "/all-requests"):
            self.assertTrue(importer.caller_ok(path, "10.24.25.6"))
            self.assertFalse(importer.caller_ok(path, "10.24.25.2"))

    def test_torrent_only_from_abr(self):
        self.assertTrue(importer.caller_ok("/prowlarr/torrent?hash=x", "10.24.25.4"))
        self.assertFalse(importer.caller_ok("/prowlarr/torrent", "10.24.25.2"))

    def test_abr_by_name_on_the_egress_network(self):
        resolve = {"audiobookrequest": ["10.24.26.2"]}.get
        self.assertTrue(importer.caller_ok("/prowlarr/torrent", "10.24.26.2", lambda n: resolve(n, [])))
        self.assertFalse(importer.caller_ok("/prowlarr/torrent", "10.24.26.3", lambda n: resolve(n, [])))

    def test_other_paths_unchanged(self):
        self.assertTrue(importer.caller_ok("/health", "10.24.25.1"))
        self.assertTrue(importer.caller_ok("/prowlarr/api/v1/search", "10.24.25.2"))


class WedgeFallbackTest(unittest.TestCase):
    def test_indexer_body_with_the_wedge_switched(self):
        idx = {"id": 1, "fields": [{"name": "useFreeleechWedge", "value": True}, {"name": "mamId", "value": "x"}]}
        off = importer.with_wedge(idx, False)
        self.assertEqual({f["name"]: f["value"] for f in off["fields"]}, {"useFreeleechWedge": False, "mamId": "x"})
        self.assertIs(idx["fields"][0]["value"], True)


class AbsSearchAllTest(unittest.TestCase):
    def test_book_hits_of_every_language_library_are_merged(self):
        en = {"book": [{"libraryItem": {"id": "1"}}], "series": [], "authors": []}
        de = {"book": [{"libraryItem": {"id": "2"}}], "series": [], "authors": []}
        other = {"book": []}
        merged = importer.merge_searches([en, de, other])
        self.assertEqual([b["libraryItem"]["id"] for b in merged["book"]], ["1", "2"])

    def test_only_book_libraries_are_searched(self):
        libs = [{"id": "en", "mediaType": "book"}, {"id": "pod", "mediaType": "podcast"}, {"id": "de", "mediaType": "book"}]
        self.assertEqual(importer.book_library_ids(libs), ["en", "de"])


class AllRequestsTest(unittest.TestCase):
    def wish(self, asin, downloaded, *reqs):
        return {"book": {"asin": asin, "title": f"T{asin}", "authors": ["Jane Doe", "X"], "cover_image": f"https://img/{asin}.jpg",
                         "downloaded": downloaded},
                "requests": [{"user_username": u, "updated_at": t} for u, t in reqs]}

    def test_every_request_with_name_date_and_status(self):
        wishlist = [self.wish("A1", False, ("jane", "2026-10-20T10:00:00")),
                    self.wish("A2", True, ("john", "2026-10-25T10:00:00"), ("jane", "2026-10-26T09:00:00")),
                    self.wish("A3", True, ("jane", "2026-10-24T10:00:00"))]
        jobs = {"h2": {"asin": "A2", "state": "pending"}, "h3": {"asin": "A3", "state": "done"}}
        rows = importer.all_requests(wishlist, [], jobs)
        self.assertEqual([(r["title"], r["requested_by"], r["status"]) for r in rows],
                         [("TA2", "jane", "downloading"), ("TA2", "john", "downloading"),
                          ("TA3", "jane", "in library"), ("TA1", "jane", "open")])
        self.assertEqual(rows[0]["author"], "Jane Doe, X")
        self.assertEqual(rows[0]["cover"], "https://img/A2.jpg")
        self.assertEqual(rows[0]["requested"], "2026-10-26T09:00:00")

    def test_merge_wait_is_downloading_and_abs_hit_without_job_is_in_library(self):
        rows = importer.all_requests([self.wish("A1", True, ("jane", "2026-10-20T10:00:00")),
                                      self.wish("A2", False, ("jane", "2026-10-21T10:00:00"))],
                                     [], {"h": {"asin": "A2", "state": "merge-wait"}})
        self.assertEqual({r["title"]: r["status"] for r in rows}, {"TA1": "in library", "TA2": "downloading"})

    def test_manual_requests_are_listed(self):
        manual = [{"title": "M", "authors": ["A"], "user_username": "jane", "updated_at": "2026-10-22T10:00:00", "downloaded": False}]
        rows = importer.all_requests([], manual, {})
        self.assertEqual([(r["title"], r["requested_by"], r["status"], r["cover"]) for r in rows], [("M", "jane", "open", None)])
