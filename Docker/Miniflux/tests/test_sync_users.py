import importlib.util
import io
import json
import os
import pathlib
import stat
import sys
import tempfile
import unittest
import urllib.error

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
spec = importlib.util.spec_from_file_location("sync_users", HERE.parent / "scripts" / "sync_users.py")
su = importlib.util.module_from_spec(spec)
spec.loader.exec_module(su)

ADMIN_KEY = "a" * 64


def http_error(code, text=""):
    return urllib.error.HTTPError("http://fake", code, "err", {}, io.BytesIO(text.encode()))


class FakeMiniflux:
    """In-memory stand-in for the Miniflux REST API paths the sync uses."""

    def __init__(self):
        self.users, self.keys, self.cats, self.feeds = {}, {ADMIN_KEY: 1}, {}, {}
        self.next_id = 100
        self.calls = []
        self.fail_urls = set()
        self.checked = {}
        self.now = "2026-01-01T10:00:00Z"
        self.add_user(1, "jane-admin", admin=True)

    def _id(self):
        self.next_id += 1
        return self.next_id

    def add_user(self, uid, name, admin=False):
        self.users[uid] = {"id": uid, "username": name, "is_admin": admin, "custom_js": ""}
        self.cats[uid] = {self._id(): "All"}
        self.feeds[uid] = {}

    def add_feed(self, uid, url, category):
        cid = next((c for c, t in self.cats[uid].items() if t == category), None) or self.add_cat(uid, category)
        fid = self._id()
        self.feeds[uid][fid] = (url, cid)
        return fid

    def add_cat(self, uid, title):
        cid = self._id()
        self.cats[uid][cid] = title
        return cid

    def urls(self, uid):
        return {u: self.cats[uid][c] for u, c in self.feeds[uid].values()}

    def call(self, method, path, key, body=None, timeout=None):
        self.calls.append((method, path, key))
        uid = self.keys.get(key)
        if uid is None:
            raise http_error(401, '{"error_message":"Access Unauthorized"}')
        if path == "/users" and method == "GET":
            if not self.users[uid]["is_admin"]:
                raise http_error(403)
            return list(self.users.values())
        if path == "/me":
            return self.users[uid]
        if path.startswith("/users/") and method == "PUT":
            if not self.users[uid]["is_admin"]:
                raise http_error(403)
            self.users[int(path.split("/")[2])].update(body)
            return self.users[int(path.split("/")[2])]
        if path == "/categories" and method == "GET":
            return [{"id": c, "title": t, "user_id": uid} for c, t in self.cats[uid].items()]
        if path == "/categories" and method == "POST":
            if body["title"] in self.cats[uid].values():
                raise http_error(400, "category already exists")
            return {"id": self.add_cat(uid, body["title"])}
        if path.startswith("/categories/") and method == "DELETE":
            cid = int(path.split("/")[2])
            del self.cats[uid][cid]
            self.feeds[uid] = {f: v for f, v in self.feeds[uid].items() if v[1] != cid}
            return None
        if path == "/feeds" and method == "GET":
            return [{"id": f, "feed_url": u, "category": {"id": c, "title": self.cats[uid][c]}, "checked_at": self.checked.get(f, "2026-01-01T09:00:00.123456Z")}
                    for f, (u, c) in self.feeds[uid].items()]
        if path == "/feeds" and method == "POST":
            if body["feed_url"] in self.fail_urls:
                raise http_error(500, f'fetch failed: Get "{body["feed_url"]}": timeout')
            if body["feed_url"] in self.urls(uid):
                raise http_error(400, "This feed already exists")
            fid = self._id()
            self.feeds[uid][fid] = (body["feed_url"], body["category_id"])
            return {"feed_id": fid}
        if path.startswith("/feeds/") and path.endswith("/refresh") and method == "PUT":
            fid = int(path.split("/")[2])
            assert fid in self.feeds[uid]
            self.checked[fid] = self.now
            return None
        if path.startswith("/feeds/") and method == "PUT":
            fid = int(path.split("/")[2])
            self.feeds[uid][fid] = (self.feeds[uid][fid][0], body["category_id"])
            return {}
        if path.startswith("/feeds/") and method == "DELETE":
            del self.feeds[uid][int(path.split("/")[2])]
            return None
        raise AssertionError(f"unexpected call {method} {path}")


class Harness:
    def __init__(self):
        self.mf = FakeMiniflux()
        self.state = {}
        self.upserts = []
        self.mf.add_feed(1, "https://github.com/traefik/traefik/releases.atom", "Releases")
        self.mf.add_feed(1, "http://vl-web:10001/w.atom?X-FEED-KEY=secret1", "Watchlist")
        self.mf.add_cat(1, "KEV")

    def ensure_keys(self, rows):
        self.upserts.append(rows)
        for uid, token in rows:
            self.mf.keys[token] = uid

    def run(self):
        self.mf.calls.clear()
        self.state, lines = su.sync(self.mf.call, ADMIN_KEY, "jane-admin", self.state, self.ensure_keys)
        return lines

    def writes(self):
        return [(m, p) for m, p, _ in self.mf.calls if m != "GET"]


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.h.mf.add_user(2, "sam-user")

    def test_new_user_gets_every_admin_feed_and_category(self):
        self.h.run()
        self.assertEqual(self.h.mf.urls(2), self.h.mf.urls(1))
        self.assertEqual(set(self.h.mf.cats[2].values()), set(self.h.mf.cats[1].values()))

    def test_missing_user_key_is_created_once_then_reused(self):
        self.h.run()
        self.h.run()
        self.assertEqual(self.h.upserts, [[(2, su.user_key(ADMIN_KEY, 2))]])

    def test_second_run_writes_nothing(self):
        self.h.run()
        self.h.run()
        self.assertEqual(self.h.writes(), [])

    def test_feed_removed_by_admin_is_removed_but_own_feed_stays(self):
        self.h.run()
        self.h.mf.add_feed(2, "https://own.example.com/feed", "All")
        traefik = next(f for f, (u, _) in self.h.mf.feeds[1].items() if "traefik" in u)
        del self.h.mf.feeds[1][traefik]
        self.h.run()
        self.assertNotIn("https://github.com/traefik/traefik/releases.atom", self.h.mf.urls(2))
        self.assertIn("https://own.example.com/feed", self.h.mf.urls(2))

    def test_feed_the_user_had_before_the_sync_is_never_removed(self):
        self.h.mf.add_feed(2, "https://github.com/traefik/traefik/releases.atom", "Mine")
        self.h.run()
        self.h.mf.feeds[1] = {f: v for f, v in self.h.mf.feeds[1].items() if "traefik" not in v[0]}
        self.h.run()
        self.assertEqual(self.h.mf.urls(2)["https://github.com/traefik/traefik/releases.atom"], "Mine")

    def test_feed_added_or_moved_by_admin_follows(self):
        self.h.run()
        self.h.mf.add_feed(1, "https://github.com/goauthentik/authentik/releases.atom", "Releases")
        watch = next(f for f, (u, _) in self.h.mf.feeds[1].items() if "vl-web" in u)
        kev = next(c for c, t in self.h.mf.cats[1].items() if t == "KEV")
        self.h.mf.feeds[1][watch] = (self.h.mf.feeds[1][watch][0], kev)
        self.h.run()
        self.assertEqual(self.h.mf.urls(2), self.h.mf.urls(1))

    def test_category_removed_by_admin_goes_when_empty_and_stays_with_own_feeds(self):
        self.h.mf.add_cat(1, "Old")
        self.h.mf.add_cat(1, "Shared")
        self.h.run()
        self.h.mf.add_feed(2, "https://own.example.com/feed", "Shared")
        self.h.mf.cats[1] = {c: t for c, t in self.h.mf.cats[1].items() if t not in ("Old", "Shared")}
        self.h.run()
        self.assertNotIn("Old", self.h.mf.cats[2].values())
        self.assertIn("Shared", self.h.mf.cats[2].values())
        self.assertIn("https://own.example.com/feed", self.h.mf.urls(2))

    def test_admins_are_left_alone(self):
        self.h.mf.add_user(3, "other-admin", admin=True)
        before = (dict(self.h.mf.feeds[1]), dict(self.h.mf.cats[1]))
        self.h.run()
        self.assertEqual((self.h.mf.feeds[1], self.h.mf.cats[1]), before)
        self.assertEqual(self.h.mf.feeds[3], {})
        self.assertFalse([k for m, p, k in self.h.mf.calls if k == su.user_key(ADMIN_KEY, 3)])

    def test_only_feed_and_category_endpoints_are_used_for_users(self):
        self.h.run()
        paths = {p.split("/")[1] for m, p, k in self.h.mf.calls if k != ADMIN_KEY}
        self.assertLessEqual(paths, {"me", "feeds", "categories"})

    def test_failed_subscribe_is_masked_and_retried_next_run(self):
        url = "http://vl-web:10001/w.atom?X-FEED-KEY=secret1"
        self.h.mf.fail_urls.add(url)
        lines = self.h.run()
        self.assertFalse(any("secret1" in line for line in lines))
        self.assertTrue(any("FAILED" in line for line in lines))
        self.h.mf.fail_urls.clear()
        self.h.run()
        self.assertIn(url, self.h.mf.urls(2))

    def test_output_never_shows_the_feed_key(self):
        lines = self.h.run()
        self.assertTrue(lines)
        self.assertFalse(any("secret1" in line for line in lines))

    def test_user_copy_behind_the_admins_is_refreshed_once(self):
        self.h.run()
        watch = lambda uid: next(f for f, (u, _) in self.h.mf.feeds[uid].items() if "vl-web" in u)
        self.h.mf.checked[watch(1)] = "2026-01-01T09:30:00+00:00"
        self.h.mf.checked[watch(2)] = "2026-01-01T09:05:00Z"
        lines = self.h.run()
        self.assertIn(("PUT", f"/feeds/{watch(2)}/refresh"), self.h.writes())
        self.assertEqual([p for m, p in self.h.writes() if p.endswith("/refresh")], [f"/feeds/{watch(2)}/refresh"])
        self.assertTrue(any("refresh" in line and "secret1" not in line for line in lines))
        self.h.run()
        self.assertEqual(self.h.writes(), [])

    def test_user_copy_a_few_minutes_behind_is_refreshed(self):
        self.h.run()
        watch = lambda uid: next(f for f, (u, _) in self.h.mf.feeds[uid].items() if "vl-web" in u)
        self.h.mf.checked[watch(1)] = "2026-01-01T09:04:00Z"
        self.h.mf.checked[watch(2)] = "2026-01-01T09:00:00Z"
        self.h.run()
        self.assertEqual(self.h.writes(), [("PUT", f"/feeds/{watch(2)}/refresh")])

    def test_user_copy_fetched_within_a_minute_of_the_admins_is_left_alone(self):
        self.h.run()
        watch = lambda uid: next(f for f, (u, _) in self.h.mf.feeds[uid].items() if "vl-web" in u)
        self.h.mf.checked[watch(1)] = "2026-01-01T09:00:40Z"
        self.h.mf.checked[watch(2)] = "2026-01-01T09:00:00Z"
        self.h.run()
        self.assertEqual(self.h.writes(), [])

    def test_deleted_users_leave_the_state(self):
        self.h.run()
        self.assertIn("2", self.h.state)
        del self.h.mf.users[2]
        self.h.run()
        self.assertNotIn("2", self.h.state)


class TechstackLinkTest(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.h.mf.add_user(2, "sam-user")

    def test_every_user_and_the_admin_get_the_techstack_link(self):
        self.h.run()
        for uid in (1, 2):
            self.assertIn('"/techstack"', self.h.mf.users[uid]["custom_js"])
            self.assertIn("header-menu", self.h.mf.users[uid]["custom_js"])
            self.assertIn("\"Tech stack\"", self.h.mf.users[uid]["custom_js"])

    def test_own_custom_js_stays(self):
        self.h.mf.users[2]["custom_js"] = "console.log('mine');"
        self.h.run()
        self.assertIn("console.log('mine');", self.h.mf.users[2]["custom_js"])
        self.assertIn('"/techstack"', self.h.mf.users[2]["custom_js"])

    def test_outdated_link_is_replaced_not_doubled(self):
        self.h.mf.users[2]["custom_js"] = su.LINK_START + "\nold();\n" + su.LINK_END + "\nmine();"
        self.h.run()
        js = self.h.mf.users[2]["custom_js"]
        self.assertEqual(js.count(su.LINK_START), 1)
        self.assertNotIn("old();", js)
        self.assertIn("mine();", js)

    def test_link_is_set_only_once(self):
        self.h.run()
        self.h.run()
        self.assertFalse([p for m, p in self.h.writes() if p.startswith("/users/")])


class KeyTest(unittest.TestCase):
    def test_user_key_is_stable_per_user_and_hides_the_admin_key(self):
        k2 = su.user_key(ADMIN_KEY, 2)
        self.assertEqual(k2, su.user_key(ADMIN_KEY, 2))
        self.assertNotEqual(k2, su.user_key(ADMIN_KEY, 3))
        self.assertRegex(k2, "^[0-9a-f]{64}$")
        self.assertNotIn(ADMIN_KEY, k2)

    def test_upsert_sql_is_idempotent_and_quoted(self):
        sql = su.upsert_sql([(2, "ab12"), (7, "cd34")])
        self.assertIn("(2, 'ab12', 'feed-sync')", sql)
        self.assertIn("(7, 'cd34', 'feed-sync')", sql)
        self.assertIn("ON CONFLICT (user_id, description) DO UPDATE SET token = EXCLUDED.token", sql)
        with self.assertRaises(ValueError):
            su.upsert_sql([(2, "x'; drop table users; --")])

    def test_keys_travel_on_stdin_not_argv(self):
        seen = {}

        def fake_run(argv, input, check, capture_output):
            seen["argv"], seen["input"] = argv, input
        su.run_sql("SELECT 'tok123';", run=fake_run)
        self.assertNotIn("tok123", " ".join(seen["argv"]))
        self.assertIn(b"tok123", seen["input"])


class StateFileTest(unittest.TestCase):
    def test_missing_file_is_empty_and_saved_file_is_private(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "state.json"
            self.assertEqual(su.load_state(path), {})
            su.save_state(path, {"2": {"feeds": ["u"], "categories": ["c"]}})
            self.assertEqual(su.load_state(path), {"2": {"feeds": ["u"], "categories": ["c"]}})
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
