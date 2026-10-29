"""Run: python3 -m unittest discover -s Docker/Audiobook-Requests/importer"""
import unittest
from unittest import mock

import importer
from test_importer import Live
import library

LIBS = [{"id": "en", "name": "[EN] Audiobooks", "mediaType": "book"}, {"id": "de", "name": "[DE] Hörbücher", "mediaType": "book"},
        {"id": "pod", "name": "Podcasts", "mediaType": "podcast"}]


def item(i, lib="en", asin=None, size=100, tags=(), explicit=False, title=None, added=1770425220177):
    return {"id": i, "libraryId": lib, "size": size, "addedAt": added, "path": "/audiobooks/EN/x", "relPath": "x", "ino": "1",
            "media": {"duration": 3600.5, "tags": list(tags), "numAudioFiles": 1,
                      "metadata": {"title": title or "T" + i, "subtitle": "Sub", "authorName": "Jane Doe", "narratorName": "John Roe",
                                   "seriesName": "Saga #1", "asin": asin, "explicit": explicit, "language": "English",
                                   "description": "long text", "publishedYear": "2010"}}}


ITEMS = {"en": [item("1", asin="A1"), item("2", tags=["kids"]), item("3", explicit=True)], "de": [item("4", lib="de", size=300)]}


def user(name, type_="user", libs=(), all_libs=True, all_tags=True, tags=(), not_tags=False, explicit=True, oidc=True):
    return {"username": name, "type": type_, "isActive": True, "hasOpenIDLink": oidc, "librariesAccessible": list(libs), "itemTagsSelected": list(tags),
            "token": "SECRET-TOKEN", "email": "x@example.com",
            "permissions": {"accessAllLibraries": all_libs, "accessAllTags": all_tags, "selectedTagsNotAccessible": not_tags,
                            "accessExplicitContent": explicit}}


def ids(rows):
    return [r["id"] for r in rows]


class Visibility(unittest.TestCase):
    def test_user_is_found_by_exact_username(self):
        users = [user("jane"), user("Jane2")]
        self.assertEqual(library.abs_user(users, "jane")["username"], "jane")
        self.assertIsNone(library.abs_user(users, "JANE"))
        self.assertIsNone(library.abs_user(users, ""))
        self.assertIsNone(library.abs_user([{**user("off"), "isActive": False}], "off"))

    def test_only_accounts_created_by_the_holy_grail_login(self):
        self.assertIsNone(library.abs_user([user("local", oidc=False)], "local"))
        self.assertIsNone(library.abs_user([{k: v for k, v in user("old").items() if k != "hasOpenIDLink"}], "old"))
        self.assertEqual(library.abs_user([user("adm", "admin")], "adm")["username"], "adm")

    def test_never_the_root_account(self):
        self.assertIsNone(library.abs_user([user("root", "root")], "root"))
        self.assertIsNone(library.abs_user([user("root", "root", oidc=False)], "root"))

    def test_all_access_sees_every_book_library(self):
        self.assertEqual(ids(library.visible(user("a"), LIBS, ITEMS)), ["1", "2", "3", "4"])

    def test_only_accessible_libraries(self):
        self.assertEqual(ids(library.visible(user("a", libs=["de"], all_libs=False), LIBS, ITEMS)), ["4"])

    def test_explicit_hidden_without_permission(self):
        self.assertEqual(ids(library.visible(user("a", explicit=False), LIBS, ITEMS)), ["1", "2", "4"])

    def test_selected_tags_only(self):
        self.assertEqual(ids(library.visible(user("a", all_tags=False, tags=["kids"]), LIBS, ITEMS)), ["2"])

    def test_selected_tags_not_accessible(self):
        self.assertEqual(ids(library.visible(user("a", all_tags=False, tags=["kids"], not_tags=True), LIBS, ITEMS)), ["1", "3", "4"])

    def test_root_sees_everything(self):
        self.assertEqual(ids(library.visible(user("r", "root", all_libs=False, explicit=False), LIBS, ITEMS)), ["1", "2", "3", "4"])


class Rows(unittest.TestCase):
    def test_row_fields_and_nothing_else(self):
        r = library.row(item("1", asin="A1"), {"en": "[EN] Audiobooks"})
        self.assertEqual(r, {"id": "1", "title": "T1", "subtitle": "Sub", "author": "Jane Doe", "narrator": "John Roe", "series": "Saga #1",
                             "duration": 3600, "size": 100, "added": "2026-02-07T00:47:00Z", "library": "[EN] Audiobooks", "asin": "A1",
                             "year": "2010"})

    def test_listing_has_no_secrets_paths_or_descriptions(self):
        out = library.listing(user("a"), [user("a")], LIBS, ITEMS)
        text = repr(out)
        for leak in ("SECRET-TOKEN", "example.com", "/audiobooks/EN", "long text", "relPath"):
            self.assertNotIn(leak, text)
        self.assertEqual(out["count"], 4)
        self.assertEqual(out["abs"], "https://audiobookshelf.holy-grail.ch/item/")

    def test_viewer_without_abs_account_gets_nothing(self):
        out = library.listing(None, [], LIBS, ITEMS)
        self.assertEqual((out["count"], out["items"], out["noAbsUser"]), (0, [], True))


class Sizes(unittest.TestCase):
    def test_abs_size_by_asin_then_the_torrent_size_while_downloading(self):
        jobs = {"h1": {"asin": "A1", "hash": "h1", "state": "done"}, "h9": {"asin": "A9", "hash": "h9", "state": "pending"}}
        torrents = [{"hash": "h9", "size": 555}, {"hash": "h1", "size": 999}]
        self.assertEqual(library.sizes(ITEMS, jobs, torrents, {"1", "2", "3", "4"}), {"A1": 100, "A9": 555})

    def test_only_books_the_viewer_may_see(self):
        items = {"en": [item("1", asin="A1"), item("2", asin="A2", explicit=True)], "de": [item("4", lib="de", asin="A4", size=300)]}
        jobs = {"h2": {"asin": "A2", "hash": "h2", "state": "pending"}, "h9": {"asin": "A9", "hash": "h9", "state": "pending"}}
        torrents = [{"hash": "h2", "size": 777}, {"hash": "h9", "size": 555}]
        self.assertEqual(library.sizes(items, jobs, torrents, {"1"}), {"A1": 100, "A9": 555})
        self.assertEqual(library.sizes(items, jobs, torrents, set()), {"A9": 555})

    def test_all_requests_sizes_are_the_viewers_too(self):
        with Live() as live, mock.patch.dict(importer.CALLERS, {"/all-requests": ("127.0.0.1",)}), \
                mock.patch.object(importer, "book_sizes", return_value={}) as sizes, \
                mock.patch.object(importer, "http_json", return_value=[]), mock.patch.object(importer, "load", return_value={}):
            self.assertEqual(live.request("GET", "/all-requests", headers={"X-authentik-username": "jane"})[0], 200)
        sizes.assert_called_once_with("jane")

    def test_sizes_endpoint_uses_the_viewers_abs_account(self):
        class Cache:
            def users(self):
                return [user("jane", explicit=False)]

            def books(self):
                return LIBS, {"en": [item("1", asin="A1"), item("3", asin="A3", explicit=True)]}

        class Qbit:
            def category(self):
                return []

        with mock.patch.object(importer, "ABS_CACHE", Cache()), mock.patch.object(importer, "QBIT", Qbit(), create=True), \
                mock.patch.object(importer, "load", return_value={}):
            self.assertEqual(importer.book_sizes("jane"), {"A1": 100})
            self.assertEqual(importer.book_sizes("nobody"), {})
            self.assertEqual(importer.book_sizes(""), {})


class AllRequestsSize(unittest.TestCase):
    def test_rows_carry_asin_and_size(self):
        wish = [{"book": {"asin": "A1", "title": "T", "authors": [], "downloaded": True}, "requests": [{"user_username": "j", "updated_at": "2026-10-20"}]}]
        rows = importer.all_requests(wish, [], {}, {"A1": 123})
        self.assertEqual((rows[0]["asin"], rows[0]["size"]), ("A1", 123))
        self.assertIsNone(importer.all_requests(wish, [], {})[0]["size"])


class Callers(unittest.TestCase):
    def test_library_paths_only_from_books_proxy(self):
        for path in ("/library", "/library-cover/abc", "/sizes"):
            self.assertTrue(importer.caller_ok(path, "10.24.25.6"), path)
            self.assertFalse(importer.caller_ok(path, "10.24.25.2"), path)

    def test_cover_id_must_be_plain(self):
        self.assertEqual(library.cover_id("/library-cover/li_8a7b-c9"), "li_8a7b-c9")
        for bad in ("/library-cover/../x", "/library-cover/a?b", "/library-cover/", "/library-cover/a/b"):
            self.assertIsNone(library.cover_id(bad), bad)
