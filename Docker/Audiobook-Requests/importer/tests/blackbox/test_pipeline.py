"""The import pipeline: webhook -> qBittorrent -> copy into the library -> merge wait -> ABS scan and match. Downloads are never changed."""
import json
import os
import time
import unittest
from pathlib import Path

import harness
from harness import ServiceTest, legacy_bug

HASH = "f" * 40
WEBHOOK = {"hash": HASH, "asin": "B000TEST01", "title": "The Yellow Wallpaper", "authors": "Charlotte Perkins Gilman",
           "source": "The Yellow Wallpaper by Charlotte Perkins Gilman [ENG / M4B]", "indexer": "MyAnonamouse"}
DEST = "EN/Charlotte Perkins Gilman/The Yellow Wallpaper"


def snapshot(path):
    """Every file under path with its bytes and mtime: the seeding copy must come out identical."""
    out = {}
    for p in sorted(Path(path).rglob("*")):
        if p.is_file():
            out[str(p)] = (p.read_bytes(), p.stat().st_mtime_ns)
    return out


def torrent(svc, h, content, category="abr", progress=1.0, added=None, size=1234):
    return {"hash": h, "category": category, "progress": progress, "added_on": added or int(time.time()), "size": size,
            "content_path": str(content), "name": Path(content).name}


class SingleFile(ServiceTest):
    @classmethod
    def prepare(cls, svc):
        src = svc.downloads / "Yellow Wallpaper.m4b"
        src.write_bytes(b"m4b-bytes" * 100)
        cls.src = src
        cls.before = snapshot(svc.downloads)
        svc.qbit.torrents = [torrent(svc, HASH, src)]
        svc.abs.search = {"en": {"book": [{"libraryItem": {"id": "li1", "path": f"/audiobooks/{DEST}"}}, {"libraryItem": {"id": "other", "path": "/audiobooks/EN/x"}}]}}
        svc.abs.details = {"li1": {"id": "li1", "media": {"metadata": {"authors": [{"id": "au1", "name": "Charlotte Perkins Gilman"}]}}}}

    def test_copy_scan_and_match(self):
        self.assertEqual(self.svc.request("POST", "/abr", peer="abr", body=WEBHOOK)[0], 204)
        job = self.svc.wait_state(lambda k, j: k == HASH, "done")
        dest = self.svc.library / DEST
        self.assertEqual([p.name for p in dest.iterdir()], ["Yellow Wallpaper.m4b"])
        self.assertEqual((dest / "Yellow Wallpaper.m4b").read_bytes(), self.src.read_bytes())
        self.assertEqual(snapshot(self.svc.downloads), self.before)
        self.assertEqual([p.name for p in self.svc.library.rglob(".*")], [])
        self.assertEqual(job["dest"], DEST)
        self.assertEqual(job["book"], {"title": "The Yellow Wallpaper", "authors": ["Charlotte Perkins Gilman"]})
        self.assertIsNone(job["region"])
        self.assertAlmostEqual(job["imported"], time.time(), delta=15)
        job = self.svc.wait_for(lambda: self.svc.jobs()[HASH].get("matched") and self.svc.jobs()[HASH], what="matched")
        scans = self.svc.abs.named("POST", "/api/libraries/en/scan")
        self.assertEqual(len(scans), 1)
        self.assertEqual(scans[0].headers.get("authorization"), "Bearer abs-importer-key")
        self.assertLess(job["scanned"], job["matched"])
        match = self.svc.abs.named("POST", "/api/items/li1/match")
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0].json(), {"provider": "audible", "asin": "B000TEST01", "title": "The Yellow Wallpaper",
                                           "author": "Charlotte Perkins Gilman", "overrideCover": True, "overrideDetails": True})
        self.assertEqual(match[0].headers.get("content-type"), "application/json")
        search = self.svc.abs.named("GET", "/api/libraries/en/search")
        self.assertEqual(search[0].query, {"q": ["The Yellow Wallpaper"], "limit": ["25"]})
        authors = self.svc.abs.named("POST", "/api/authors/au1/match")
        self.assertEqual([a.json() for a in authors], [{"q": "Charlotte Perkins Gilman", "region": "us"}])
        self.assertEqual(self.svc.abs.named("POST", "/api/items/other/match"), [])
        time.sleep(2.5)
        self.assertEqual(len(self.svc.abs.named("POST", "/api/libraries/en/scan")), 1, "scan and match happen once")
        self.assertEqual(len(self.svc.abs.named("POST", "/api/items/li1/match")), 1)
        self.assertEqual(snapshot(self.svc.downloads), self.before)


class MultiFile(ServiceTest):
    @classmethod
    def prepare(cls, svc):
        src = svc.downloads / "Torrent Folder"
        (src / "CD1").mkdir(parents=True)
        (src / "01 - Intro.mp3").write_bytes(b"1")
        (src / "CD1" / "02.mp3").write_bytes(b"2")
        (src / "cover.jpg").write_bytes(b"jpg")
        cls.src = src
        cls.before = snapshot(svc.downloads)
        svc.qbit.torrents = [torrent(svc, HASH, src)]

    def test_merge_wait_then_done_and_scanned(self):
        self.svc.request("POST", "/abr", peer="abr", body=dict(WEBHOOK, source="X by Y [GER / MP3]"))
        job = self.svc.wait_state(lambda k, j: k == HASH, "merge-wait")
        dest = self.svc.library / job["dest"]
        self.assertEqual(job["dest"], "DE/Charlotte Perkins Gilman/The Yellow Wallpaper", "the MAM language flag names the folder without Audible")
        self.assertEqual(sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*")), ["01 - Intro.mp3", "CD1 - 02.mp3", "cover.jpg"])
        self.assertEqual((dest / "CD1 - 02.mp3").read_bytes(), b"2")
        self.assertEqual(snapshot(self.svc.downloads), self.before)
        time.sleep(2.5)
        self.assertEqual([c for c in self.svc.abs.calls if c.route.endswith("/scan")], [], "no scan before the merge")
        self.assertEqual(self.svc.jobs()[HASH]["state"], "merge-wait")
        for f in ("01 - Intro.mp3", "CD1 - 02.mp3"):
            (dest / f).unlink()
        (dest / "merged.m4b").write_bytes(b"m")
        self.svc.wait_state(lambda k, j: k == HASH, "done")
        self.svc.wait_for(lambda: self.svc.abs.named("POST", "/api/libraries/de/scan"), what="scan of the DE library after the merge")
        self.assertEqual(snapshot(self.svc.downloads), self.before)


class MergeWaitTimesOut(ServiceTest):
    ENV = {"MERGE_WAIT_HOURS": "0"}

    @classmethod
    def prepare(cls, svc):
        src = svc.downloads / "Parts"
        src.mkdir()
        (src / "Part 1.m4b").write_bytes(b"1")
        (src / "Part 2.m4b").write_bytes(b"2")
        svc.qbit.torrents = [torrent(svc, HASH, src)]

    def test_done_after_the_wait_even_without_a_merge(self):
        self.svc.request("POST", "/abr", peer="abr", body=WEBHOOK)
        job = self.svc.wait_state(lambda k, j: k == HASH, "done")
        self.assertNotIn("scanned", job) if not self.svc.abs.named("POST", "/api/libraries/en/scan") else None
        self.svc.wait_for(lambda: self.svc.abs.named("POST", "/api/libraries/en/scan"), what="scan")


class AlreadyInLibrary(ServiceTest):
    @classmethod
    def prepare(cls, svc):
        (svc.library / DEST).mkdir(parents=True)
        (svc.library / DEST / "old.m4b").write_bytes(b"old")
        src = svc.downloads / "new.m4b"
        src.write_bytes(b"new")
        svc.qbit.torrents = [torrent(svc, HASH, src)]

    def test_existing_book_is_never_overwritten(self):
        self.svc.request("POST", "/abr", peer="abr", body=WEBHOOK)
        job = self.svc.wait_state(lambda k, j: k == HASH, "exists")
        self.assertEqual(job["dest"], DEST)
        self.assertEqual([p.name for p in (self.svc.library / DEST).iterdir()], ["old.m4b"])
        self.assertEqual((self.svc.library / DEST / "old.m4b").read_bytes(), b"old")
        time.sleep(2)
        self.assertEqual(self.svc.abs.calls, [])


class WrongCategoryAndIncomplete(ServiceTest):
    @classmethod
    def prepare(cls, svc):
        (svc.downloads / "a.m4b").write_bytes(b"a")
        (svc.downloads / "b.m4b").write_bytes(b"b")
        svc.qbit.torrents = [torrent(svc, "1" * 40, svc.downloads / "a.m4b", category="other"),
                             torrent(svc, "2" * 40, svc.downloads / "b.m4b", progress=0.5)]

    def test_other_category_fails_and_incomplete_waits(self):
        self.svc.request("POST", "/abr", peer="abr", body=dict(WEBHOOK, hash="1" * 40))
        self.svc.request("POST", "/abr", peer="abr", body=dict(WEBHOOK, hash="2" * 40, title="Other"))
        job = self.svc.wait_state(lambda k, j: k == "1" * 40, "failed")
        self.assertEqual(job["error"], "category is 'other', not 'abr'")
        time.sleep(2.5)
        self.assertEqual(self.svc.jobs()["2" * 40]["state"], "pending")
        self.assertEqual(list(self.svc.library.iterdir()), [])
        self.svc.qbit.torrents[1]["progress"] = 1
        self.svc.wait_state(lambda k, j: k == "2" * 40, "done")


class MissingTorrent(ServiceTest):
    ENV = {"GIVE_UP_DAYS": "0"}

    def test_gives_up_after_the_deadline(self):
        self.svc.request("POST", "/abr", peer="abr", body=WEBHOOK)
        job = self.svc.wait_state(lambda k, j: k == HASH, "failed")
        self.assertEqual(job["error"], "torrent never appeared in qBittorrent")


class Unbound(ServiceTest):
    @classmethod
    def prepare(cls, svc):
        (svc.downloads / "manual.m4b").write_bytes(b"manual")
        svc.qbit.torrents = [torrent(svc, "0" * 40, svc.downloads / "old.m4b", added=int(time.time()) - 3000)]

    def test_binds_the_next_abr_torrent_then_imports(self):
        self.svc.request("POST", "/abr", peer="abr", body=dict(WEBHOOK, hash="{torrentInfoHash}", title="Manual Pick"))
        key = next(k for k in self.svc.jobs() if k.startswith("unbound-"))
        time.sleep(1.5)
        self.assertEqual(self.svc.jobs()[key]["state"], "unbound", "nothing new to bind yet")
        self.svc.qbit.torrents.append(torrent(self.svc, HASH, self.svc.downloads / "manual.m4b", progress=0.3))
        job = self.svc.wait_state(lambda k, j: k == HASH, "pending")
        self.assertEqual((job["hash"], job["title"]), (HASH, "Manual Pick"))
        self.assertNotIn(key, self.svc.jobs())
        self.svc.qbit.torrents[-1]["progress"] = 1
        self.svc.wait_state(lambda k, j: k == HASH, "done")
        self.assertTrue((self.svc.library / "EN/Charlotte Perkins Gilman/Manual Pick/manual.m4b").exists())


class QbitSession(ServiceTest):
    @classmethod
    def prepare(cls, svc):
        (svc.downloads / "x.m4b").write_bytes(b"x")
        svc.qbit.torrents = [torrent(svc, HASH, svc.downloads / "x.m4b", progress=0.5)]

    def test_login_with_the_secret_and_relogin_after_an_expired_session(self):
        self.svc.request("POST", "/abr", peer="abr", body=WEBHOOK)
        self.svc.wait_for(lambda: self.svc.qbit.named("GET", "/api/v2/torrents/info"), what="first qBittorrent poll")
        login = self.svc.qbit.named("POST", "/api/v2/auth/login")[0]
        self.assertIn("password=qbit-secret", login.body.decode())
        self.assertIn("username=admin", login.body.decode())
        self.assertTrue(login.headers.get("referer", "").startswith(self.svc.qbit.url))
        self.svc.qbit.sessions.clear()
        self.svc.qbit.reset()
        self.svc.qbit.torrents[0]["progress"] = 1
        self.svc.wait_state(lambda k, j: k == HASH, "done")
        self.assertGreaterEqual(len(self.svc.qbit.named("POST", "/api/v2/auth/login")), 1)
        self.assertTrue(any(c.method == "GET" and c.route == "/api/v2/torrents/info" for c in self.svc.qbit.calls))


class NoAbsKey(ServiceTest):
    ABS_KEY = ""

    @classmethod
    def prepare(cls, svc):
        (svc.downloads / "x.m4b").write_bytes(b"x")
        svc.qbit.torrents = [torrent(svc, HASH, svc.downloads / "x.m4b")]

    def test_import_without_scan_or_match(self):
        self.svc.request("POST", "/abr", peer="abr", body=WEBHOOK)
        job = self.svc.wait_state(lambda k, j: k == HASH, "done")
        time.sleep(2.5)
        self.assertEqual(self.svc.abs.calls, [])
        self.assertNotIn("scanned", self.svc.jobs()[HASH])
        self.assertNotIn("matched", self.svc.jobs()[HASH])


class MatchGivesUp(ServiceTest):
    ENV = {"MATCH_GIVE_UP_HOURS": "0"}

    @classmethod
    def prepare(cls, svc):
        (svc.downloads / "x.m4b").write_bytes(b"x")
        svc.qbit.torrents = [torrent(svc, HASH, svc.downloads / "x.m4b")]

    def test_item_never_appears(self):
        self.svc.request("POST", "/abr", peer="abr", body=WEBHOOK)
        job = self.svc.wait_for(lambda: self.svc.jobs().get(HASH, {}).get("matched") and self.svc.jobs()[HASH], what="gave up")
        self.assertEqual(job["matched"], "gave up: item never appeared in ABS")
        self.assertEqual(self.svc.abs.named("POST", "/api/items/li1/match"), [])


class WithoutAsin(ServiceTest):
    @classmethod
    def prepare(cls, svc):
        (svc.downloads / "x.m4b").write_bytes(b"x")
        svc.qbit.torrents = [torrent(svc, HASH, svc.downloads / "x.m4b")]

    @legacy_bug("audible(None) returns a bare None that step() unpacks: a job without ASIN never imports")
    def test_a_job_without_asin_still_imports_from_the_webhook_names(self):
        self.svc.request("POST", "/abr", peer="abr", body=dict(WEBHOOK, asin="{bookASIN}"))
        job = self.svc.wait_state(lambda k, j: k == HASH, "done")
        self.assertEqual(job["dest"], DEST)


@unittest.skipUnless(harness.AUDIBLE_MOCK, "needs AUDIBLE_BASE (Rust): the Python calls api.audible.com directly")
class AudibleNaming(ServiceTest):
    @classmethod
    def prepare(cls, svc):
        (svc.downloads / "x.m4b").write_bytes(b"x")
        svc.qbit.torrents = [torrent(svc, HASH, svc.downloads / "x.m4b")]
        svc.audible.products["B000TEST01"] = {"title": "The Final Empire", "authors": [{"name": "Brandon Sanderson"}],
                                              "series": [{"title": "Mistborn Series", "sequence": "1"}], "language": "english",
                                              "format_type": "unabridged", "narrators": [{"name": "Michael Kramer"}]}
        svc.abs.search = {"en": {"book": [{"libraryItem": {"id": "li1", "path": "/audiobooks/EN/Brandon Sanderson/Mistborn/01 - The Final Empire"}}]}}
        svc.abs.details = {"li1": {"id": "li1", "media": {"metadata": {"authors": [{"id": "au1", "name": "Brandon Sanderson"}]}}}}

    def test_audible_names_the_folder_and_the_match_uses_the_region(self):
        self.svc.request("POST", "/abr", peer="abr", body=WEBHOOK)
        job = self.svc.wait_state(lambda k, j: k == HASH, "done")
        self.assertEqual(job["dest"], "EN/Brandon Sanderson/Mistborn/01 - The Final Empire")
        self.assertEqual(job["region"], "com")
        self.assertEqual(job["book"], {"title": "The Final Empire", "authors": ["Brandon Sanderson"]})
        self.svc.wait_for(lambda: self.svc.abs.named("POST", "/api/items/li1/match"), what="match")
        self.assertEqual(self.svc.abs.named("POST", "/api/items/li1/match")[0].json()["provider"], "audible")
        audible = self.svc.audible.calls[0]
        self.assertEqual(audible.route, "/audible.com/1.0/catalog/products/B000TEST01")
        self.assertEqual(audible.query["response_groups"], ["series,contributors,product_desc,product_attrs,product_extended_attrs"])


if __name__ == "__main__":
    unittest.main()
