#!/usr/bin/env python3
"""Tests for usage_collector.py and usage_beefy.py.   python3 test_usage.py"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usage_beefy as bf  # noqa: E402
import usage_collector as uc  # noqa: E402


def seerr_req(i, user, typ="movie", ts="2026-10-20T10:00:00.000Z", **who):
    by = {"id": 1, "email": "x@example.com", "username": user, "displayName": user}
    by.update(who)
    return {"id": i, "type": typ, "createdAt": ts, "requestedBy": by}


class SeerrFetch(unittest.TestCase):
    def test_paginates_until_total_and_labels_users(self):
        reqs = [seerr_req(i, "jane" if i % 2 else "joe") for i in range(1, 8)]
        calls = []

        def get(path):
            calls.append(path)
            q = dict(p.split("=") for p in path.split("?")[1].split("&"))
            take, skip = int(q["take"]), int(q["skip"])
            return {"pageInfo": {"results": len(reqs)}, "results": reqs[skip:skip + take]}

        rows = bf.fetch_seerr(get, page_size=3)
        self.assertEqual(len(calls), 3)
        self.assertEqual([r["id"] for r in rows], list(range(1, 8)))
        self.assertEqual(rows[0], {"id": 1, "user": "jane", "media_type": "movie", "ts": "2026-10-20T10:00:00.000Z"})
        self.assertNotIn("email", str(rows))

    def test_user_label_prefers_jellyfin_username(self):
        r = seerr_req(1, "x", jellyfinUsername="Jelly", displayName="Disp")
        self.assertEqual(bf.seerr_user(r["requestedBy"]), "Jelly")
        self.assertEqual(bf.seerr_user({"id": 9}), "user9")


def act(i, typ, user, item, date):
    return {"Id": i, "Type": typ, "UserId": user, "ItemId": item, "Date": date}


class JellyfinFetch(unittest.TestCase):
    def setUp(self):
        self.users = [{"Id": "u1", "Name": "Alice"}, {"Id": "u2", "Name": "Bob"}]
        self.items = {"m1": {"Id": "m1", "Type": "Movie", "RunTimeTicks": 100 * 60 * 10**7},
                      "e1": {"Id": "e1", "Type": "Episode", "RunTimeTicks": 40 * 60 * 10**7},
                      "a1": {"Id": "a1", "Type": "Audio", "RunTimeTicks": 10**9}}

    def run_fetch(self, entries, now="2026-10-26T12:00:00Z", page=2):
        def get(path):
            if path.startswith("/Users"):
                return self.users
            if path.startswith("/Items"):
                ids = path.split("Ids=")[1].split("&")[0].split(",")
                return {"Items": [self.items[i] for i in ids if i in self.items]}
            q = dict(p.split("=") for p in path.split("?")[1].split("&"))
            s, n = int(q["startIndex"]), int(q["limit"])
            return {"TotalRecordCount": len(entries), "Items": entries[s:s + n]}
        return bf.fetch_jellyfin(get, now=bf.parse_iso(now), page_size=page)

    def test_pairs_start_and_stop_and_splits_film_episode(self):
        e = [act(5, "VideoPlaybackStopped", "u2", "e1", "2026-10-25T21:30:00.5Z"),
             act(4, "VideoPlayback", "u2", "e1", "2026-10-25T21:00:00.5Z"),
             act(3, "VideoPlaybackStopped", "u1", "m1", "2026-10-25T20:30:00.0000000Z"),
             act(2, "VideoPlayback", "u1", "m1", "2026-10-25T20:00:00.0000000Z"),
             act(1, "SessionStarted", "u1", None, "2026-10-25T19:00:00Z")]
        plays = {p["user"]: p for p in self.run_fetch(e)}
        self.assertEqual((plays["Alice"]["kind"], plays["Alice"]["seconds"]), ("film", 1800))
        self.assertEqual((plays["Bob"]["kind"], plays["Bob"]["seconds"]), ("episode", 1800))
        self.assertEqual(plays["Alice"]["item"], "m1")
        self.assertEqual(plays["Alice"]["ts"], "2026-10-25T20:00:00.0000000Z")

    def test_duration_capped_at_runtime(self):
        e = [act(2, "VideoPlaybackStopped", "u1", "e1", "2026-10-25T23:00:00Z"),
             act(1, "VideoPlayback", "u1", "e1", "2026-10-25T10:00:00Z")]
        self.assertEqual(self.run_fetch(e)[0]["seconds"], 40 * 60)

    def test_in_progress_skipped_old_unpaired_counted_with_zero(self):
        e = [act(2, "VideoPlayback", "u1", "m1", "2026-10-26T11:30:00Z"),
             act(1, "VideoPlayback", "u2", "e1", "2026-10-24T11:30:00Z")]
        plays = self.run_fetch(e)
        self.assertEqual([(p["user"], p["seconds"]) for p in plays], [("Bob", 0)])

    def test_repeated_start_closes_the_previous_one_as_zero(self):
        e = [act(3, "VideoPlaybackStopped", "u1", "m1", "2026-10-25T20:30:00Z"),
             act(2, "VideoPlayback", "u1", "m1", "2026-10-25T20:10:00Z"),
             act(1, "VideoPlayback", "u1", "m1", "2026-10-25T20:00:00Z")]
        plays = sorted(self.run_fetch(e), key=lambda p: p["ts"])
        self.assertEqual([p["seconds"] for p in plays], [0, 1200])

    def test_deleted_item_is_other_and_audio_ignored(self):
        e = [act(4, "VideoPlaybackStopped", "u1", "gone", "2026-10-25T20:10:00Z"),
             act(3, "VideoPlayback", "u1", "gone", "2026-10-25T20:00:00Z"),
             act(2, "AudioPlaybackStopped", "u1", "a1", "2026-10-25T19:10:00Z"),
             act(1, "AudioPlayback", "u1", "a1", "2026-10-25T19:00:00Z")]
        plays = self.run_fetch(e)
        self.assertEqual([(p["kind"], p["seconds"]) for p in plays], [("other", 600)])

    def test_unknown_user(self):
        e = [act(2, "VideoPlaybackStopped", "zz", "m1", "2026-10-25T20:10:00Z"),
             act(1, "VideoPlayback", "zz", "m1", "2026-10-25T20:00:00Z")]
        self.assertEqual(self.run_fetch(e)[0]["user"], "unknown")


class Kinds(unittest.TestCase):
    def test_cache_fills_deleted_items_and_learns_new_ones(self):
        plays = [{"user": "a", "kind": "other", "item": "i1", "seconds": 1, "ts": "t"},
                 {"user": "a", "kind": "film", "item": "i2", "seconds": 1, "ts": "t"},
                 {"user": "a", "kind": "other", "item": "i3", "seconds": 1, "ts": "t"}]
        cache = uc.apply_kinds(plays, {"i1": "episode"})
        self.assertEqual([p["kind"] for p in plays], ["episode", "film", "other"])
        self.assertEqual(cache, {"i1": "episode", "i2": "film"})

    def test_cache_file_roundtrip_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "kinds.json")
            self.assertEqual(uc.load_kinds(p), {})
            uc.save_kinds(p, {"i": "film"})
            self.assertEqual(uc.load_kinds(p), {"i": "film"})


class Lines(unittest.TestCase):
    def test_escape_and_timestamps(self):
        self.assertEqual(uc.esc("a b,c=d"), r"a\ b\,c\=d")
        self.assertEqual(uc.iso_ns("2026-10-25T20:00:00.5Z"), 1792958400500000000)
        self.assertEqual(uc.iso_ns("2026-10-25T20:00:00.1234567Z"), 1792958400123456000)
        self.assertEqual(uc.iso_ns("2026-10-25 20:00:00.250 +00:00"), 1792958400250000000)

    def test_lines(self):
        data = {"seerr": [{"id": 3, "user": "Jane Doe", "media_type": "tv", "ts": "2026-10-25T20:00:00.000Z"}],
                "jellyfin": [{"user": "Bob", "kind": "film", "seconds": 90, "ts": "2026-10-25T20:00:00Z"}]}
        lines = uc.beefy_lines(data)
        self.assertEqual(lines[0], r"seerr_request,user=Jane\ Doe,media_type=tv count=1i,id=3i 1792958400000000000")
        self.assertEqual(lines[1], "jellyfin_play,user=Bob,kind=film plays=1i,seconds=90i 1792958400000000000")

    def test_same_input_same_lines(self):
        data = {"seerr": [{"id": 3, "user": "j", "media_type": "tv", "ts": "2026-10-25T20:00:00Z"}], "jellyfin": []}
        self.assertEqual(uc.beefy_lines(data), uc.beefy_lines(data))


class Abs(unittest.TestCase):
    def test_sessions_per_user(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "abs.sqlite")
            c = sqlite3.connect(p)
            c.execute("create table users (id text, username text, token text)")
            c.execute("create table playbackSessions (id text, userId text, timeListening real, createdAt text)")
            c.execute("insert into users values ('u1','alezauron','SECRET')")
            c.executemany("insert into playbackSessions values (?,?,?,?)", [
                ("s1", "u1", 600.7, "2026-10-17 09:04:33.467 +00:00"),
                ("s2", "gone", 5, "2026-10-17 10:00:00.000 +00:00"),
                ("s3", "u1", 0, "2026-10-17 11:00:00.000 +00:00")])
            c.commit()
            c.close()
            rows = uc.abs_sessions(p)
            self.assertEqual([(r["user"], r["seconds"]) for r in rows], [("alezauron", 600), ("unknown", 5)])
            lines = uc.abs_lines(rows)
            self.assertEqual(lines[0], "abs_listen,user=alezauron sessions=1i,seconds=600i 1792227873467000000")
            self.assertNotIn("SECRET", str(rows))


class Run(unittest.TestCase):
    def test_beefy_asleep_skips_beefy_but_writes_abs(self):
        written, ran = [], []
        rc = uc.run(kinds_file=None, probe=lambda: False, fetch_beefy=lambda: ran.append(1), abs_rows=lambda: [
            {"user": "a", "seconds": 5, "ts": "2026-10-17 09:00:00.000 +00:00"}], write=written.append)
        self.assertEqual((rc, ran), (0, []))
        self.assertEqual(len(written[0]), 1)
        self.assertTrue(written[0][0].startswith("abs_listen"))

    def test_beefy_awake_writes_everything(self):
        written = []
        data = {"seerr": [{"id": 1, "user": "j", "media_type": "movie", "ts": "2026-10-25T20:00:00Z"}], "jellyfin": []}
        rc = uc.run(kinds_file=None, probe=lambda: True, fetch_beefy=lambda: data, abs_rows=lambda: [], write=written.append)
        self.assertEqual(rc, 0)
        self.assertEqual(len(written[0]), 1)

    def test_beefy_error_keeps_abs_and_fails(self):
        written = []

        def boom():
            raise RuntimeError("ssh failed")
        rc = uc.run(kinds_file=None, probe=lambda: True, fetch_beefy=boom, abs_rows=lambda: [
            {"user": "a", "seconds": 5, "ts": "2026-10-17 09:00:00.000 +00:00"}], write=written.append)
        self.assertEqual(rc, 1)
        self.assertEqual(len(written[0]), 1)


if __name__ == "__main__":
    unittest.main()
