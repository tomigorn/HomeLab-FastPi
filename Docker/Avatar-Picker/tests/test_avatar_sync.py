import base64, contextlib, hashlib, importlib.util, json, pathlib, re, shutil, socket, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("avatar_sync", HERE.parent / "scripts" / "avatar-sync.py")
sync = importlib.util.module_from_spec(spec); spec.loader.exec_module(sync)

BASE = "https://avatars.example"


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.queue, self.state = self.tmp / "queue.json", self.tmp / "state" / "synced.json"
        self.pushed, self.opened = [], []

    def target(self, name, gate=None, fail_for=(), needs=None, broken=False, crash=False):
        @contextlib.contextmanager
        def open_session():
            self.opened.append(name)
            if broken:
                raise sync.SyncError("ssh tunnel failed")
            def push(user, aid):
                if crash:
                    raise KeyError("unexpected")
                if user in fail_for:
                    raise sync.SyncError("down")
                self.pushed.append((name, user, aid))
                return "set"
            yield push
        return sync.Target(name, lambda: gate, open_session, needs)

    def run_sync(self, targets, reconcile=False):
        return sync.run(self.queue, self.state, targets, lambda: "2026-10-27T18:00:00Z", reconcile)

    def synced(self):
        return json.loads(self.state.read_text())

    def test_nothing_queued_opens_nothing(self):
        self.assertEqual(self.run_sync([self.target("jellyfin")]), 0)
        self.assertEqual(self.opened, [])

    def test_gated_target_keeps_the_pick_pending_others_run(self):
        self.queue.write_text(json.dumps({"me": {"avatar": "creeper", "at": "t1"}}))
        self.assertEqual(self.run_sync([self.target("jellyfin", gate="beefy asleep"), self.target("ha")]), 0)
        self.assertEqual((self.opened, self.pushed), (["ha"], [("ha", "me", "creeper")]))
        self.assertEqual(self.synced()["me"]["targets"], {"ha": "creeper"})
        self.assertEqual(self.run_sync([self.target("jellyfin"), self.target("ha")]), 0)
        self.assertEqual(self.pushed[-1], ("jellyfin", "me", "creeper"))
        self.assertEqual(self.synced()["me"]["targets"], {"ha": "creeper", "jellyfin": "creeper"})

    def test_synced_pick_is_not_pushed_again(self):
        self.queue.write_text(json.dumps({"me": {"avatar": "creeper", "at": "t1"}}))
        self.run_sync([self.target("ha")]); self.run_sync([self.target("ha")])
        self.assertEqual((self.opened, self.pushed), (["ha"], [("ha", "me", "creeper")]))

    def test_reconcile_pushes_everything_again(self):
        self.queue.write_text(json.dumps({"me": {"avatar": "creeper", "at": "t1"}}))
        self.run_sync([self.target("ha")]); self.run_sync([self.target("ha")], reconcile=True)
        self.assertEqual(self.pushed, [("ha", "me", "creeper")] * 2)

    def test_new_target_catches_up_on_old_picks(self):
        self.queue.write_text(json.dumps({"me": {"avatar": "creeper", "at": "t1"}}))
        self.run_sync([self.target("jellyfin")])
        self.run_sync([self.target("jellyfin"), self.target("ha")])
        self.assertEqual(self.pushed, [("jellyfin", "me", "creeper"), ("ha", "me", "creeper")])

    def test_failure_stays_pending_other_users_and_targets_continue(self):
        self.queue.write_text(json.dumps({"a": {"avatar": "fox", "at": "t1"}, "b": {"avatar": "owl", "at": "t2"}}))
        self.assertEqual(self.run_sync([self.target("jellyfin", fail_for={"a"}), self.target("ha")]), 1)
        self.assertEqual(self.pushed, [("jellyfin", "b", "owl"), ("ha", "a", "fox"), ("ha", "b", "owl")])
        self.assertEqual(self.synced()["a"]["targets"], {"ha": "fox"})

    def test_broken_or_crashing_target_does_not_block_the_others(self):
        self.queue.write_text(json.dumps({"a": {"avatar": "fox", "at": "t1"}}))
        rc = self.run_sync([self.target("jellyfin", broken=True), self.target("seerr", crash=True), self.target("ha")])
        self.assertEqual(rc, 1)
        self.assertEqual(self.pushed, [("ha", "a", "fox")])
        self.assertEqual(self.synced()["a"]["targets"], {"ha": "fox"})

    def test_dependent_target_waits_for_its_prerequisite(self):
        self.queue.write_text(json.dumps({"a": {"avatar": "fox", "at": "t1"}, "b": {"avatar": "owl", "at": "t2"}}))
        self.run_sync([self.target("jellyfin", fail_for={"a"}), self.target("seerr", needs="jellyfin")])
        self.assertEqual(self.pushed, [("jellyfin", "b", "owl"), ("seerr", "b", "owl")])
        self.pushed.clear()
        self.run_sync([self.target("jellyfin"), self.target("seerr", needs="jellyfin")])
        self.assertEqual(self.pushed, [("jellyfin", "a", "fox"), ("seerr", "a", "fox")])

    def test_dependent_target_skipped_when_prerequisite_fails_during_reconcile(self):
        self.queue.write_text(json.dumps({"a": {"avatar": "fox", "at": "t1"}}))
        self.run_sync([self.target("jellyfin"), self.target("seerr", needs="jellyfin")])
        self.pushed.clear()
        self.run_sync([self.target("jellyfin", fail_for={"a"}), self.target("seerr", needs="jellyfin")], reconcile=True)
        self.assertEqual(self.pushed, [])

    def test_unsafe_queue_entries_are_refused(self):
        self.queue.write_text(json.dumps({"me; rm -rf /": {"avatar": "fox"}, "me": {"avatar": "../x"}, "ok": "x", "n": {"avatar": 3}}))
        self.assertEqual(self.run_sync([self.target("ha")]), 1)
        self.assertEqual(self.pushed, [])

    def test_old_state_format_counts_as_jellyfin_and_seerr_done(self):
        self.queue.write_text(json.dumps({"me": {"avatar": "creeper", "at": "t1"}}))
        self.state.parent.mkdir(); self.state.write_text(json.dumps({"me": {"avatar": "creeper", "at": "t1", "synced": "t2"}}))
        self.run_sync([self.target("jellyfin"), self.target("seerr", needs="jellyfin"), self.target("ha")])
        self.assertEqual(self.pushed, [("ha", "me", "creeper")])


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


class Pushes(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "img").mkdir(); (self.tmp / "img-local").mkdir()
        (self.tmp / "img-local" / "creeper.png").write_bytes(b"\x89PNGcreeper")
        self.dirs = [self.tmp / "img", self.tmp / "img-local"]
        self.images = []

    class Jf:
        def __init__(self, outer, known):
            self.outer, self.known = outer, known
        def user_id(self, name):
            return "abc123" if name == self.known else None
        def set_image(self, uid, png):
            self.outer.images.append((uid, png))

    def test_jellyfin_sets_the_png(self):
        push = sync.jellyfin_push(self.Jf(self, "me"), self.dirs)
        self.assertEqual(push("me", "creeper"), "image set")
        self.assertEqual(self.images, [("abc123", b"\x89PNGcreeper")])
        self.assertEqual(push("x", "creeper"), "no user")

    def test_missing_image_file(self):
        for push in (sync.jellyfin_push(self.Jf(self, "me"), self.dirs), sync.ha_push(None, BASE, self.dirs),
                     sync.nextcloud_push(None, {"me": "u1"}, self.dirs)):
            with self.assertRaises(sync.SyncError):
                push("me", "gone")
        self.assertEqual(self.images, [])

    def test_seerr_gets_the_picker_url(self):
        calls = []
        push = sync.seerr_push(lambda u, url: calls.append((u, url)) or {"status": "jellyfin-refreshed"}, BASE + "/")
        self.assertEqual(push("me", "creeper"), "jellyfin-refreshed")
        self.assertEqual(calls, [("me", BASE + "/img/creeper.png")])

    class Ha:
        def __init__(self, persons):
            self.list, self.updates = persons, []
        def persons(self):
            return self.list
        def set_picture(self, pid, url):
            self.updates.append((pid, url))

    def test_ha_person_by_slug_of_the_username(self):
        ha = self.Ha([{"id": "admin", "name": "admin", "picture": None},
                      {"id": "tomigorn", "name": "Tomigorn", "picture": BASE + "/img/fox.png"},
                      {"id": "tomigorn_admin", "name": "Tomigorn (admin)", "picture": None}])
        push = sync.ha_push(ha, BASE, self.dirs)
        self.assertEqual(push("tomigorn", "creeper"), "picture set")
        self.assertEqual(push("tomigorn-admin", "creeper"), "picture set")
        self.assertEqual(ha.updates, [("tomigorn", BASE + "/img/creeper.png"), ("tomigorn_admin", BASE + "/img/creeper.png")])

    def test_ha_person_by_name_unchanged_and_missing(self):
        ha = self.Ha([{"id": "person_7", "name": "Alezauron", "picture": BASE + "/img/creeper.png"}])
        push = sync.ha_push(ha, BASE, self.dirs)
        self.assertEqual(push("alezauron", "creeper"), "unchanged")
        self.assertEqual(push("nobody", "creeper"), "no person")
        self.assertEqual(ha.updates, [])

    def test_nextcloud_maps_the_user_and_sends_the_png(self):
        calls = []
        def runner(uid, png):
            calls.append((uid, png)); return "set"
        push = sync.nextcloud_push(runner, {"me": "a" * 64}, self.dirs)
        self.assertEqual(push("me", "creeper"), "set")
        self.assertEqual(calls, [("a" * 64, b"\x89PNGcreeper")])
        self.assertEqual(push("other", "creeper"), "no user")
        with self.assertRaises(sync.SyncError):
            sync.nextcloud_push(runner, {"me": "x; reboot"}, self.dirs)("me", "creeper")


class Gates(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)

    def test_secret_file_gate(self):
        f = self.tmp / "ha_token"
        gate = sync.file_gate(f, "no secrets/ha_token")
        self.assertEqual(gate(), "inactive: no secrets/ha_token")
        f.write_text("  \n")
        self.assertEqual(gate(), "inactive: no secrets/ha_token")
        f.write_text("tok\n")
        self.assertIsNone(gate())

    def test_all_gates(self):
        self.assertEqual(sync.all_gates(lambda: None, lambda: "beefy asleep")(), "beefy asleep")
        self.assertIsNone(sync.all_gates(lambda: None, lambda: None)())

    def test_nextcloud_users_file(self):
        f = self.tmp / "nextcloud_users.json"
        self.assertEqual(sync.read_map(f), {})
        f.write_text('{"me": "abc"}')
        self.assertEqual(sync.read_map(f), {"me": "abc"})


def ws_server_frame(opcode, payload):
    n = len(payload)
    head = bytes([0x80 | opcode]) + (bytes([n]) if n < 126 else bytes([126]) + n.to_bytes(2, "big") if n < 65536 else bytes([127]) + n.to_bytes(8, "big"))
    return head + payload


def ws_server_read(conn):
    def exact(k):
        b = b""
        while len(b) < k:
            c = conn.recv(k - len(b))
            if not c:
                raise EOFError
            b += c
        return b
    h = exact(2)
    n = h[1] & 0x7F
    if n == 126:
        n = int.from_bytes(exact(2), "big")
    elif n == 127:
        n = int.from_bytes(exact(8), "big")
    assert h[1] & 0x80, "client frames must be masked"
    mask = exact(4)
    data = bytes(b ^ mask[i % 4] for i, b in enumerate(exact(n)))
    return h[0] & 0x0F, data


class FakeHa:
    def __init__(self, token="t0k", persons=None, ping_first=False):
        self.token, self.ping_first = token, ping_first
        self.persons = persons or [{"id": "tomigorn", "name": "Tomigorn", "user_id": "u1", "picture": None}]
        self.received = []
        self.sock = socket.socket(); self.sock.bind(("127.0.0.1", 0)); self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        conn, _ = self.sock.accept()
        self.sock.close()
        with conn:
            req = b""
            while b"\r\n\r\n" not in req:
                req += conn.recv(1)
            key = re.search(rb"Sec-WebSocket-Key: (\S+)", req).group(1)
            accept = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
            path = req.split(b" ")[1]
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n")
            send = lambda m: conn.sendall(ws_server_frame(1, json.dumps(m).encode()))
            if path != b"/api/websocket":
                return
            send({"type": "auth_required"})
            try:
                while True:
                    op, data = ws_server_read(conn)
                    if op == 8:
                        return
                    if op == 10:
                        self.received.append({"type": "pong"}); continue
                    msg = json.loads(data); self.received.append(msg)
                    if msg["type"] == "auth":
                        if msg.get("access_token") != self.token:
                            send({"type": "auth_invalid", "message": "Invalid access token"}); return
                        send({"type": "auth_ok"})
                        if self.ping_first:
                            conn.sendall(ws_server_frame(9, b"hi"))
                    elif msg["type"] == "person/list":
                        send({"id": msg["id"] - 1, "type": "event", "event": {}})
                        big = [dict(p) for p in self.persons] + [{"id": f"p{i}", "name": "x" * 200, "picture": None} for i in range(400)]
                        send({"id": msg["id"], "type": "result", "success": True, "result": {"storage": big, "config": []}})
                    elif msg["type"] == "person/update":
                        if msg["person_id"] not in [p["id"] for p in self.persons]:
                            send({"id": msg["id"], "type": "result", "success": False, "error": {"code": "not_found", "message": "x"}}); continue
                        send({"id": msg["id"], "type": "result", "success": True, "result": {}})
            except EOFError:
                return


class HomeAssistant(unittest.TestCase):
    def test_lists_persons_and_sets_a_picture(self):
        fake = FakeHa(ping_first=True)
        with sync.ha_client("127.0.0.1", fake.port, "t0k") as ha:
            persons = ha.persons()
            ha.set_picture("tomigorn", BASE + "/img/creeper.png")
        self.assertIn("tomigorn", [p["id"] for p in persons])
        self.assertGreater(len(persons), 400)
        self.assertEqual(fake.received[0], {"type": "auth", "access_token": "t0k"})
        self.assertIn({"type": "pong"}, fake.received)
        upd = [m for m in fake.received if m["type"] == "person/update"][0]
        self.assertEqual({k: upd[k] for k in ("person_id", "picture")}, {"person_id": "tomigorn", "picture": BASE + "/img/creeper.png"})

    def test_bad_token_is_a_sync_error_without_the_token(self):
        fake = FakeHa(token="right")
        with self.assertRaises(sync.SyncError) as cm:
            with sync.ha_client("127.0.0.1", fake.port, "wrong-secret") as ha:
                ha.persons()
        self.assertNotIn("wrong-secret", str(cm.exception))

    def test_failed_command_is_a_sync_error(self):
        fake = FakeHa()
        with self.assertRaises(sync.SyncError):
            with sync.ha_client("127.0.0.1", fake.port, "t0k") as ha:
                ha.set_picture("nobody", BASE + "/img/creeper.png")

    def test_ha_down_is_a_sync_error(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
        with self.assertRaises(sync.SyncError):
            with sync.ha_client("127.0.0.1", port, "t0k"):
                pass


class Check(unittest.TestCase):
    def test_reports_in_sync_and_mismatched_persons(self):
        persons = [{"id": "tomigorn", "name": "Tomigorn", "picture": BASE + "/img/creeper.png"},
                   {"id": "tomigorn_admin", "name": "Tomigorn (admin)", "picture": BASE + "/img/fox.png"}]
        picks = {"tomigorn": "creeper", "tomigorn-admin": "colour-pink", "nobody": "owl"}
        self.assertEqual(sync.ha_check(persons, picks, BASE), "mismatch tomigorn-admin")
        picks["tomigorn-admin"] = "fox"
        self.assertEqual(sync.ha_check(persons, picks, BASE), "ok 2/2")


class NextcloudRunner(unittest.TestCase):
    def test_runs_php_in_the_container_over_ssh(self):
        calls = []
        def ok(cmd, stdin):
            calls.append((cmd, stdin)); return 0, "set\n", ""
        call = sync.nextcloud_runner("tower-direct", ok)
        self.assertEqual(call("a" * 64, b"PNG"), "set")
        cmd, stdin = calls[0]
        self.assertEqual(cmd[:3], ["ssh", "-o", "BatchMode=yes"])
        self.assertIn("tower-direct", cmd)
        self.assertIn("docker exec -i -u www-data nextcloud php -r", cmd[-1])
        self.assertTrue(cmd[-1].endswith(" " + "a" * 64))
        self.assertEqual(stdin, b"PNG")
        with self.assertRaises(sync.SyncError):
            sync.nextcloud_runner("h", lambda c, s: (1, "", "boom"))("u", b"")
        with self.assertRaises(sync.SyncError):
            sync.nextcloud_runner("h", lambda c, s: (0, "weird", ""))("u", b"")


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
