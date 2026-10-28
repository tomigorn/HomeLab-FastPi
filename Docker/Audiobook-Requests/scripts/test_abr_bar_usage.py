#!/usr/bin/env python3
"""scripts/abr_bar_usage.py: Prowlarr counts per indexer window, levels, resets, subscriptions (own date or Seerr's cached list), the audiobook disks once per filesystem, Prowlarr down, and that usage.json holds only names and counts.
Usage: python3 -m unittest discover -s Docker/Audiobook-Requests/scripts"""
import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import abr_bar_usage as bu  # noqa: E402

UTC = dt.timezone.utc
TIB, GIB = 1024 ** 4, 1024 ** 3

INDEXERS = [
    {"id": 1, "name": "MyAnonamouse", "protocol": "torrent", "enable": True},
    {"id": 2, "name": "Other", "protocol": "torrent", "enable": True},
    {"id": 9, "name": "Old One", "protocol": "torrent", "enable": False},
]
LIMITS = {"Other": {"searches": 10, "downloads": 2, "window": "rolling"}}


def utc(*a):
    return dt.datetime(*a, tzinfo=UTC)


def ev(indexer_id, when, event="indexerQuery"):
    return {"id": 1, "indexerId": indexer_id, "date": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "successful": True, "eventType": event,
            "data": {"url": "https://example.com/t.php?apikey=SECRETKEY123", "host": "10.24.25.5", "source": "AudioBookRequest", "query": "Some Book"}}


def row(result, name):
    return next(r for r in result["indexers"] if r["name"] == name)


class Counting(unittest.TestCase):
    NOW = utc(2026, 10, 28, 12, 0)

    def test_unlimited_mam_counts_searches_and_grabs_over_24h(self):
        h = [ev(1, self.NOW - dt.timedelta(hours=1)), ev(1, self.NOW - dt.timedelta(hours=2), "indexerRss"),
             ev(1, self.NOW - dt.timedelta(hours=3), "releaseGrabbed"), ev(1, self.NOW - dt.timedelta(hours=25)),
             ev(1, self.NOW - dt.timedelta(hours=4), "indexerAuth")]
        r = row(bu.usage(INDEXERS, h, LIMITS, self.NOW), "MyAnonamouse")
        self.assertFalse(r["limited"])
        self.assertEqual((r["searches"]["used"], r["searches"]["limit"], r["downloads"]["used"], r["level"]), (2, None, 1, "ok"))

    def test_limited_indexer_levels_and_reset(self):
        h = [ev(2, self.NOW - dt.timedelta(hours=20), "releaseGrabbed"), ev(2, self.NOW - dt.timedelta(hours=1), "releaseGrabbed")]
        r = row(bu.usage(INDEXERS, h, LIMITS, self.NOW), "Other")
        self.assertTrue(r["limited"])
        self.assertEqual((r["downloads"]["used"], r["downloads"]["limit"], r["downloads"]["level"]), (2, 2, "full"))
        self.assertEqual(r["downloads"]["resetsAt"], "2026-10-28T16:00:00Z")
        self.assertEqual(r["level"], "full")

    def test_warn_from_70_percent(self):
        h = [ev(2, self.NOW - dt.timedelta(minutes=i + 1)) for i in range(7)]
        self.assertEqual(row(bu.usage(INDEXERS, h, LIMITS, self.NOW), "Other")["searches"]["level"], "warn")

    def test_calendar_day_window_resets_at_zurich_midnight(self):
        now = utc(2026, 7, 10, 10, 0)
        lim = {"Other": {"searches": 100, "window": "day"}}
        h = [ev(2, utc(2026, 7, 9, 22, 30)), ev(2, utc(2026, 7, 9, 21, 59))]
        s = row(bu.usage(INDEXERS, h, lim, now), "Other")["searches"]
        self.assertEqual((s["used"], s["resetsAt"]), (1, "2026-07-10T22:00:00Z"))

    def test_order_limited_first_and_disabled_hidden(self):
        self.assertEqual([r["name"] for r in bu.usage(INDEXERS, [], LIMITS, self.NOW)["indexers"]], ["Other", "MyAnonamouse"])


class Subscriptions(unittest.TestCase):
    TODAY = dt.date(2026, 10, 28)
    SEERR = [{"name": "ProtonVPN Plus", "kind": "VPN", "expires": dt.date(2026, 11, 20)}, {"name": "Eweka", "expires": dt.date(2027, 1, 1)}]

    def test_own_date_and_levels(self):
        out = bu.subscriptions([{"name": "MAM VIP", "kind": "indexer", "expires": dt.date(2026, 11, 2)}], self.TODAY)
        self.assertEqual((out[0]["daysLeft"], out[0]["level"], out[0]["expires"]), (5, "orange", "2026-11-02"))

    def test_seerr_entry_takes_the_date_from_seerrs_list(self):
        out = bu.subscriptions([{"name": "ProtonVPN Plus", "seerr": True}], self.TODAY, self.SEERR)
        self.assertEqual((out[0]["name"], out[0]["kind"], out[0]["daysLeft"], out[0]["level"]), ("ProtonVPN Plus", "VPN", 23, "yellow"))

    def test_seerr_entry_missing_in_seerrs_list_is_left_out(self):
        self.assertEqual(bu.subscriptions([{"name": "Gone", "seerr": True}], self.TODAY, self.SEERR), [])
        self.assertEqual(bu.subscriptions([{"name": "ProtonVPN Plus", "seerr": True}], self.TODAY, None), [])

    def test_lifetime(self):
        out = bu.subscriptions([{"name": "X", "lifetime": True}], self.TODAY)
        self.assertEqual((out[0]["lifetime"], out[0]["level"], out[0]["daysLeft"]), (True, "ok", None))

    def test_bad_entry_is_an_error(self):
        with self.assertRaises(ValueError):
            bu.subscriptions([{"name": "Z"}], self.TODAY)

    def test_seerr_list_from_the_cached_toml(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "limits.toml"
            p.write_text('[[subscriptions]]\nname = "ProtonVPN Plus"\nkind = "VPN"\nexpires = 2027-06-15\n')
            self.assertEqual(bu.seerr_subscriptions(p), [{"name": "ProtonVPN Plus", "kind": "VPN", "expires": dt.date(2027, 6, 15)}])
            self.assertIsNone(bu.seerr_subscriptions(pathlib.Path(d) / "missing.toml"))


class FakeStat:
    def __init__(self, total, free, frsize=4096, reserved=0):
        self.f_frsize, self.f_blocks, self.f_bavail = frsize, total // frsize, free // frsize
        self.f_bfree = self.f_bavail + reserved // frsize


def fake(table):
    """table: path -> (device, FakeStat)"""
    def statvfs(path):
        if path not in table:
            raise FileNotFoundError(path)
        return table[path][1]

    def device(path):
        if path not in table:
            raise FileNotFoundError(path)
        return table[path][0]
    return statvfs, device


DISKS = [{"name": "Library", "id": "library", "paths": ["/lib"]},
         {"name": "Downloads", "id": "downloads", "paths": ["/qbit", "/sab"]}]


class Storage(unittest.TestCase):
    def test_each_filesystem_once_with_used_total_percent(self):
        st, dev = fake({"/lib": (1, FakeStat(2 * TIB, 1.5 * TIB)), "/qbit": (2, FakeStat(2 * TIB, 0.5 * TIB)), "/sab": (2, FakeStat(2 * TIB, 0.5 * TIB))})
        lib, dl = bu.storage(DISKS, st, dev)
        self.assertEqual((lib["name"], lib["id"], lib["total"], lib["used"], lib["free"], lib["pct"], lib["level"]),
                         ("Library", "library", 2 * TIB, 0.5 * TIB, 1.5 * TIB, 25.0, "ok"))
        self.assertEqual((dl["name"], dl["id"], dl["pct"], dl["level"], dl["yellow"], dl["red"]), ("Downloads", "downloads", 75.0, "yellow", 70, 80))
        self.assertNotIn("paths", lib)

    def test_shared_filesystem_is_one_chip_naming_both(self):
        st, dev = fake({"/lib": (1, FakeStat(2 * TIB, TIB)), "/qbit": (1, FakeStat(2 * TIB, TIB)), "/sab": (1, FakeStat(2 * TIB, TIB))})
        out = bu.storage(DISKS, st, dev)
        self.assertEqual([(d["name"], d["id"]) for d in out], [("Library + Downloads", "library+downloads")])

    def test_levels_green_below_70_yellow_to_80_red_from_80(self):
        for ratio, level in {0.699: "ok", 0.70: "yellow", 0.799: "yellow", 0.80: "full", 0.97: "full"}.items():
            total = 1000 * 4096
            st, dev = fake({"/lib": (1, FakeStat(total, round(total * (1 - ratio) / 4096) * 4096))})
            self.assertEqual(bu.storage(DISKS[:1], st, dev)[0]["level"], level, ratio)

    def test_like_df_reserved_blocks_are_neither_used_nor_free(self):
        st, dev = fake({"/lib": (1, FakeStat(2000 * GIB, 1400 * GIB, reserved=100 * GIB))})
        lib = bu.storage(DISKS[:1], st, dev)[0]
        self.assertEqual((lib["total"], lib["used"], lib["free"], lib["pct"]), (2000 * GIB, 500 * GIB, 1400 * GIB, 26.3))

    def test_bar_texts_in_english_and_german(self):
        st, dev = fake({"/lib": (1, FakeStat(2 * TIB, TIB)), "/qbit": (2, FakeStat(2 * TIB, TIB)), "/sab": (2, FakeStat(2 * TIB, TIB))})
        lib, dl = bu.storage(DISKS, st, dev)
        self.assertEqual(lib["label"], {"en": "Library", "de": "Bibliothek"})
        self.assertEqual(lib["sub"], {"en": "books in Audiobookshelf", "de": "Bücher in Audiobookshelf"})
        self.assertEqual(lib["hint"]["en"], "Audiobookshelf library. From 70 % plan more space, from 80 % new books may soon not fit. Nothing is deleted automatically.")
        self.assertEqual(lib["hint"]["de"], "Audiobookshelf-Bibliothek. Ab 70 % mehr Platz einplanen, ab 80 % passen neue Bücher bald nicht mehr. Es wird nichts automatisch gelöscht.")
        self.assertEqual(dl["hint"]["en"], "Torrents keep seeding (MyAnonamouse rules), so this only grows. From 80 % make room by hand; nothing is removed automatically.")
        self.assertTrue(dl["hint"]["de"].startswith("Torrents seeden weiter (MyAnonamouse-Regeln)"))

    def test_shared_filesystem_joins_the_texts(self):
        st, dev = fake({"/lib": (1, FakeStat(2 * TIB, TIB)), "/qbit": (1, FakeStat(2 * TIB, TIB)), "/sab": (1, FakeStat(2 * TIB, TIB))})
        d = bu.storage(DISKS, st, dev)[0]
        self.assertEqual(d["label"], {"en": "Library + Downloads", "de": "Bibliothek + Downloads"})
        self.assertRegex(d["hint"]["en"], r"^Audiobookshelf library\..* Torrents keep seeding")

    def test_unreadable_path_is_skipped(self):
        st, dev = fake({"/lib": (1, FakeStat(2 * TIB, TIB))})
        self.assertEqual([d["name"] for d in bu.storage(DISKS, st, dev)], ["Library"])

    def test_default_disks_are_library_and_downloads(self):
        self.assertEqual([(d["id"], d["paths"]) for d in bu.DISKS],
                         [("library", ["/mnt/seagate-black/library/audiobooks"]),
                          ("downloads", ["/mnt/seagate-red/qbittorrent/downloads", "/mnt/seagate-red/sabnzbd/config/Downloads"])])


class Config(unittest.TestCase):
    def test_repo_config_loads(self):
        cfg = bu.load_config(HERE.parent / "abr-bar" / "limits.toml")
        self.assertIn("ProtonVPN Plus", [s["name"] for s in cfg["subscriptions"]])
        self.assertIsInstance(cfg["indexers"], dict)

    def test_bad_window_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "l.toml"
            p.write_text('[indexers."X"]\nsearches = 5\nwindow = "week"\n')
            with self.assertRaises(ValueError):
                bu.load_config(p)


class Run(unittest.TestCase):
    NOW = utc(2026, 10, 28, 12, 0)
    CFG = {"indexers": LIMITS, "subscriptions": [{"name": "ProtonVPN Plus", "seerr": True}]}
    SEERR = [{"name": "ProtonVPN Plus", "kind": "VPN", "expires": dt.date(2027, 6, 15)}]

    def disks(self):
        return fake({"/lib": (1, FakeStat(2 * TIB, TIB)), "/qbit": (2, FakeStat(2 * TIB, TIB)), "/sab": (2, FakeStat(2 * TIB, TIB))})

    def test_writes_only_names_and_counts(self):
        h = [ev(1, self.NOW - dt.timedelta(hours=1)), ev(1, self.NOW - dt.timedelta(hours=1), "releaseGrabbed")]
        calls = []

        def api(path):
            calls.append(path)
            return INDEXERS if path == "/indexer" else h
        st, dev = self.disks()
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "usage.json"
            bu.run(self.CFG, api, out, self.NOW, disks=DISKS, statvfs=st, device=dev, seerr=self.SEERR)
            text = out.read_text()
            mode = out.stat().st_mode & 0o777
        data = json.loads(text)
        self.assertEqual(mode, 0o644)
        self.assertTrue(data["ok"])
        self.assertEqual(data["generated"], "2026-10-28T12:00:00Z")
        self.assertEqual(calls, ["/indexer", "/history/since?date=2026-10-27T12:00:00Z"])
        self.assertEqual(row(data, "MyAnonamouse")["downloads"]["used"], 1)
        self.assertEqual(data["subscriptions"][0]["name"], "ProtonVPN Plus")
        self.assertEqual([s["name"] for s in data["storage"]], ["Library", "Downloads"])
        self.assertTrue(data["showUnlimited"])
        self.assertTrue(data["note"]["en"].startswith("Searches and downloads go through Prowlarr to MyAnonamouse."))
        self.assertIn("de", data["note"])
        for leak in ("apikey", "SECRETKEY", "10.24", "AudioBookRequest", "Some Book", "example.com", "/lib", "/qbit", "mam_"):
            self.assertNotIn(leak, text)

    def test_prowlarr_down_still_writes_storage_and_subscriptions(self):
        def api(path):
            raise bu.ApiError("connection refused")
        st, dev = self.disks()
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "usage.json"
            bu.run(self.CFG, api, out, self.NOW, disks=DISKS, statvfs=st, device=dev, seerr=self.SEERR)
            data = json.loads(out.read_text())
        self.assertFalse(data["ok"])
        self.assertEqual(data["indexers"], [])
        self.assertEqual(len(data["storage"]), 2)
        self.assertEqual(len(data["subscriptions"]), 1)
        self.assertNotIn("connection refused", json.dumps(data))

    def test_api_key_from_the_credential_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "config.xml"
            p.write_text("<Config><Port>9696</Port><ApiKey>0123abcd</ApiKey></Config>")
            self.assertEqual(bu.api_key(p), "0123abcd")
            p.write_text("<Config></Config>")
            with self.assertRaises(bu.ApiError):
                bu.api_key(p)


if __name__ == "__main__":
    unittest.main()
