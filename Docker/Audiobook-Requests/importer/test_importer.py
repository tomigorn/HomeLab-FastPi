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
        self.assertEqual(sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*")), ["01.mp3", "CD1", "CD1/02.mp3"])
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
