import importlib.util, io, json, pathlib, shutil, sqlite3, sys, tempfile, unittest
from contextlib import redirect_stdout

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("seerr_avatar", HERE.parent / "scripts" / "seerr-avatar.py")
sa = importlib.util.module_from_spec(spec); spec.loader.exec_module(sa)

BASE = "https://avatars.example"
JF = "70d44a367988405d8792444c1c716d9a"


class Refresh(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.db = self.tmp / "db.sqlite3"
        self.cache = self.tmp / "avatar"
        (self.cache / "somekey").mkdir(parents=True)
        (self.cache / "somekey" / "86400.1.x.png").write_bytes(b"old")
        con = sqlite3.connect(self.db)
        con.executescript(f"""
            CREATE TABLE user (id INTEGER PRIMARY KEY, avatar varchar NOT NULL, jellyfinUserId varchar, avatarETag varchar, avatarVersion varchar);
            CREATE TABLE linked_accounts (id INTEGER PRIMARY KEY, provider varchar, sub varchar, username varchar, userId integer);
            INSERT INTO user VALUES (1, '/avatarproxy/{JF}?v=null', '{JF}', NULL, '1');
            INSERT INTO user VALUES (5, '{BASE}/img/indiana-jones.png', NULL, NULL, NULL);
            INSERT INTO user VALUES (6, 'https://gravatar.example/x', NULL, NULL, NULL);
            INSERT INTO linked_accounts VALUES (1, 'holy-grail', 's1', 'jane', 1);
            INSERT INTO linked_accounts VALUES (2, 'holy-grail', 's5', 'john', 5);
            INSERT INTO linked_accounts VALUES (3, 'holy-grail', 's6', 'gravatar-fan', 6);
            INSERT INTO linked_accounts VALUES (4, 'other-idp', 's7', 'stranger', 6);
        """)
        con.commit(); con.close()

    def row(self, uid):
        con = sqlite3.connect(self.db)
        try:
            return con.execute("SELECT avatar, avatarVersion FROM user WHERE id=?", (uid,)).fetchone()
        finally:
            con.close()

    def refresh(self, user, url):
        return sa.refresh(self.db, self.cache, user, url, now_ms=1793123210625)

    def test_jellyfin_linked_user_gets_new_version_and_cache_cleared(self):
        self.assertEqual(self.refresh("jane", BASE + "/img/creeper.png"), {"status": "jellyfin-refreshed", "user": 1})
        self.assertEqual(self.row(1), (f"/avatarproxy/{JF}?v=1793123210625", "1793123210625"))
        self.assertTrue(self.cache.is_dir())
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_oidc_user_with_picker_url_gets_the_new_url(self):
        self.assertEqual(self.refresh("john", BASE + "/img/creeper.png"), {"status": "url-updated", "user": 5})
        self.assertEqual(self.row(5)[0], BASE + "/img/creeper.png")
        self.assertEqual(len(list(self.cache.iterdir())), 1)

    def test_same_url_is_left_alone(self):
        self.assertEqual(self.refresh("john", BASE + "/img/indiana-jones.png"), {"status": "unchanged", "user": 5})

    def test_foreign_avatar_is_not_overwritten(self):
        self.assertEqual(self.refresh("gravatar-fan", BASE + "/img/creeper.png"), {"status": "not-picker-avatar", "user": 6})
        self.assertEqual(self.row(6)[0], "https://gravatar.example/x")

    def test_unknown_or_other_provider_user(self):
        self.assertEqual(self.refresh("nobody", BASE + "/img/creeper.png"), {"status": "no-user"})
        self.assertEqual(self.refresh("stranger", BASE + "/img/creeper.png"), {"status": "no-user"})

    def test_bad_url_refused(self):
        for url in ("http://x/img/a.png", BASE + "/img/a.png'; DROP TABLE user;--", BASE + "/other/a.png"):
            with self.assertRaises(ValueError, msg=url):
                self.refresh("jane", url)
        self.assertEqual(self.row(1)[1], "1")

    def test_main_prints_json(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = sa.main(["john", BASE + "/img/creeper.png"], db=self.db, cache=self.cache)
        self.assertEqual((rc, json.loads(out.getvalue())), (0, {"status": "url-updated", "user": 5}))


if __name__ == "__main__":
    unittest.main()
