import base64, contextlib, importlib.util, json, pathlib, shutil, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("avatar_sync", HERE.parent / "scripts" / "avatar-sync.py")
sync = importlib.util.module_from_spec(spec); spec.loader.exec_module(sync)

BASE = "https://avatars.example"


class Pending(unittest.TestCase):
    def test_only_picks_that_differ_from_the_synced_state(self):
        queue = {"a": {"avatar": "fox", "at": "t1"}, "b": {"avatar": "owl", "at": "t2"}, "c": {"avatar": "cat", "at": "t3"}}
        synced = {"a": {"avatar": "fox", "at": "t1"}, "b": {"avatar": "cat", "at": "t0"}}
        self.assertEqual(sync.pending(queue, synced), [("b", queue["b"]), ("c", queue["c"])])

    def test_ignores_malformed_entries(self):
        self.assertEqual(sync.pending({"a": "x", "b": {"at": "t"}, "c": {"avatar": 3}}, {}), [])


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.queue, self.state = self.tmp / "queue.json", self.tmp / "state" / "synced.json"
        self.pushed, self.opened = [], 0

    def session(self, fail_for=()):
        @contextlib.contextmanager
        def open_session():
            self.opened += 1
            def push(user, aid):
                if user in fail_for:
                    raise sync.SyncError("jellyfin down")
                self.pushed.append((user, aid))
                return ["jellyfin: image set"]
            yield push
        return open_session

    def run_sync(self, up=True, fail_for=()):
        return sync.run(self.queue, self.state, lambda: up, self.session(fail_for), lambda: "2026-10-27T18:00:00Z")

    def test_nothing_queued_opens_nothing(self):
        self.assertEqual(self.run_sync(up=True), 0)
        self.assertEqual(self.opened, 0)

    def test_beefy_down_keeps_the_pick_queued(self):
        self.queue.write_text(json.dumps({"me": {"avatar": "creeper", "at": "t1"}}))
        self.assertEqual(self.run_sync(up=False), 0)
        self.assertEqual((self.opened, self.pushed), (0, []))
        self.assertFalse(self.state.exists())
        self.assertEqual(self.run_sync(up=True), 0)
        self.assertEqual(self.pushed, [("me", "creeper")])
        self.assertEqual(json.loads(self.state.read_text())["me"]["avatar"], "creeper")

    def test_synced_pick_is_not_pushed_again(self):
        self.queue.write_text(json.dumps({"me": {"avatar": "creeper", "at": "t1"}}))
        self.run_sync(); self.run_sync()
        self.assertEqual((self.opened, self.pushed), (1, [("me", "creeper")]))

    def test_failure_stays_pending_others_continue(self):
        self.queue.write_text(json.dumps({"a": {"avatar": "fox", "at": "t1"}, "b": {"avatar": "owl", "at": "t2"}}))
        self.assertEqual(self.run_sync(fail_for={"a"}), 1)
        self.assertEqual(self.pushed, [("b", "owl")])
        self.assertEqual(list(json.loads(self.state.read_text())), ["b"])

    def test_session_failure_is_an_error_not_a_crash(self):
        self.queue.write_text(json.dumps({"a": {"avatar": "fox", "at": "t1"}}))
        @contextlib.contextmanager
        def broken():
            raise sync.SyncError("ssh tunnel failed")
            yield
        self.assertEqual(sync.run(self.queue, self.state, lambda: True, broken, lambda: "t"), 1)
        self.assertFalse(self.state.exists())


class FakeJellyfin(BaseHTTPRequestHandler):
    users = []
    posts = []

    def log_message(self, *a):
        pass

    def _json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("Authorization") != 'MediaBrowser Token="k3y"':
            return self._json({}, 401)
        if self.path == "/Users":
            return self._json(self.users)
        self._json({}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        FakeJellyfin.posts.append((self.path, self.headers.get("Content-Type"), self.headers.get("Authorization"), self.rfile.read(n)))
        self.send_response(204); self.end_headers()


class Jellyfin(unittest.TestCase):
    def setUp(self):
        FakeJellyfin.users = [{"Name": "Tomigorn", "Id": "abc123"}, {"Name": "other", "Id": "def456"}]
        FakeJellyfin.posts = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeJellyfin)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close); self.addCleanup(self.httpd.shutdown)
        self.jf = sync.Jellyfin(f"http://127.0.0.1:{self.httpd.server_address[1]}", "k3y")

    def test_find_user_by_name_ignores_case(self):
        self.assertEqual(self.jf.user_id("tomigorn"), "abc123")
        self.assertIsNone(self.jf.user_id("nobody"))

    def test_set_image_posts_base64_png(self):
        self.jf.set_image("abc123", b"\x89PNGdata")
        path, ctype, auth, body = FakeJellyfin.posts[0]
        self.assertEqual(path, "/UserImage?userId=abc123")
        self.assertEqual(ctype, "image/png")
        self.assertEqual(auth, 'MediaBrowser Token="k3y"')
        self.assertEqual(base64.b64decode(body), b"\x89PNGdata")

    def test_wrong_key_is_a_sync_error(self):
        with self.assertRaises(sync.SyncError):
            sync.Jellyfin(self.jf.base, "bad").user_id("tomigorn")


class Push(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "img").mkdir(); (self.tmp / "img-local").mkdir()
        (self.tmp / "img-local" / "creeper.png").write_bytes(b"\x89PNGcreeper")
        self.dirs = [self.tmp / "img", self.tmp / "img-local"]
        self.images, self.seerr_calls = [], []

    class Jf:
        def __init__(self, outer, known):
            self.outer, self.known = outer, known
        def user_id(self, name):
            return "abc123" if name == self.known else None
        def set_image(self, uid, png):
            self.outer.images.append((uid, png))

    def seerr(self, result):
        def call(user, url):
            self.seerr_calls.append((user, url))
            return result
        return call

    def test_sets_jellyfin_image_then_refreshes_seerr(self):
        notes = sync.push("me", "creeper", self.Jf(self, "me"), self.seerr({"status": "jellyfin-refreshed"}), self.dirs, BASE)
        self.assertEqual(self.images, [("abc123", b"\x89PNGcreeper")])
        self.assertEqual(self.seerr_calls, [("me", BASE + "/img/creeper.png")])
        self.assertEqual(notes, ["jellyfin: image set", "seerr: jellyfin-refreshed"])

    def test_no_jellyfin_user_still_updates_seerr(self):
        notes = sync.push("me", "creeper", self.Jf(self, "x"), self.seerr({"status": "url-updated"}), self.dirs, BASE)
        self.assertEqual(self.images, [])
        self.assertEqual(notes, ["jellyfin: no user", "seerr: url-updated"])

    def test_missing_image_file(self):
        with self.assertRaises(sync.SyncError):
            sync.push("me", "gone", self.Jf(self, "me"), self.seerr({}), self.dirs, BASE)

    def test_unsafe_names_are_refused(self):
        for user, aid in (("me; rm -rf /", "creeper"), ("me", "../creeper"), ("", "creeper")):
            with self.assertRaises(sync.SyncError, msg=(user, aid)):
                sync.push(user, aid, self.Jf(self, "me"), self.seerr({}), self.dirs, BASE)
        self.assertEqual((self.images, self.seerr_calls), ([], []))


class SeerrRunner(unittest.TestCase):
    def test_parses_json_and_rejects_failures(self):
        calls = []
        def ok(cmd, stdin):
            calls.append((cmd, stdin)); return 0, '{"status": "unchanged"}\n', ""
        call = sync.seerr_runner("beefy-direct", b"script", ok)
        self.assertEqual(call("me", BASE + "/img/fox.png"), {"status": "unchanged"})
        cmd, stdin = calls[0]
        self.assertEqual(cmd[:3], ["ssh", "-o", "BatchMode=yes"])
        self.assertIn("beefy-direct", cmd)
        self.assertTrue(cmd[-1].endswith("python3 - me https://avatars.example/img/fox.png"))
        self.assertEqual(stdin, b"script")
        with self.assertRaises(sync.SyncError):
            sync.seerr_runner("h", b"", lambda c, s: (1, "", "boom"))("me", BASE + "/img/fox.png")
        with self.assertRaises(sync.SyncError):
            sync.seerr_runner("h", b"", lambda c, s: (0, "not json", ""))("me", BASE + "/img/fox.png")


if __name__ == "__main__":
    unittest.main()
