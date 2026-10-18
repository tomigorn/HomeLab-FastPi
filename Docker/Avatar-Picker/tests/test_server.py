import http.client, io, json, os, sys, threading, unittest, urllib.request
from http.server import ThreadingHTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import server
from authentik_api import AuthentikError

BASE = "https://avatars.example"

class FakeClient:
    def __init__(self, users, fail=False):
        self.users, self.fail, self.writes = users, fail, []
    def list_users(self):
        if self.fail: raise AuthentikError("down")
        return [dict(u, attributes=dict(u["attributes"])) for u in self.users]
    def get_user(self, pk):
        if self.fail: raise AuthentikError("down")
        for u in self.users:
            if u["pk"] == pk: return dict(u, attributes=dict(u["attributes"]))
        raise AuthentikError("no user")
    def set_attributes(self, pk, attrs):
        self.writes.append((pk, attrs))
        for u in self.users:
            if u["pk"] == pk: u["attributes"] = attrs

class ServerTest(unittest.TestCase):
    def start(self, client, secret=None):
        server.configure(client=client, base=BASE, secret=secret)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
    def tearDown(self):
        self.httpd.shutdown()
    def req(self, path, user=None, body=None, headers=None):
        h = {"X-authentik-username": user} if user else {}
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.url + path, data=data, headers=h, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def users(self):
        return [{"pk": 1, "username": "me", "attributes": {"theme": "x"}},
                {"pk": 2, "username": "other", "attributes": {"avatar": BASE + "/img/fox.png"}}]

    def test_health_and_image_public(self):
        self.start(FakeClient(self.users()))
        self.assertEqual(self.req("/healthz")[0], 200)
        code, body = self.req("/img/owl.png")
        self.assertEqual(code, 200); self.assertTrue(body.startswith(b"\x89PNG"))
        self.assertEqual(self.req("/img/../server.py")[0], 404)
        self.assertEqual(self.req("/img/nope.png")[0], 404)

    def test_page_and_state_need_identity(self):
        self.start(FakeClient(self.users()))
        self.assertEqual(self.req("/")[0], 401)
        self.assertEqual(self.req("/api/state")[0], 401)
        self.assertEqual(self.req("/", user="me")[0], 200)

    def test_state(self):
        self.start(FakeClient(self.users()))
        code, body = self.req("/api/state", user="me")
        data = json.loads(body)
        st = {a["id"]: a["status"] for a in data["avatars"]}
        self.assertEqual(data["groups"][0], {"id": "animals3d", "label": "3D animals"})
        self.assertIn("group", data["avatars"][0])
        self.assertEqual(code, 200); self.assertEqual(st["fox"], "taken"); self.assertEqual(st["owl"], "free")

    def test_pick_free_writes_merged(self):
        c = FakeClient(self.users()); self.start(c)
        code, _ = self.req("/api/pick", user="me", body={"id": "owl"})
        self.assertEqual(code, 200)
        self.assertEqual(c.writes, [(1, {"theme": "x", "avatar": BASE + "/img/owl.png"})])

    def test_pick_taken_409_no_write(self):
        c = FakeClient(self.users()); self.start(c)
        self.assertEqual(self.req("/api/pick", user="me", body={"id": "fox"})[0], 409)
        self.assertEqual(c.writes, [])

    def test_pick_bad_input(self):
        c = FakeClient(self.users()); self.start(c)
        self.assertEqual(self.req("/api/pick", user="me", body={"id": "nope"})[0], 400)
        self.assertEqual(self.req("/api/pick", user="me", body={"x": 1})[0], 400)
        self.assertEqual(self.req("/api/pick", body={"id": "owl"})[0], 401)

    def test_authentik_down_503(self):
        self.start(FakeClient(self.users(), fail=True))
        self.assertEqual(self.req("/api/state", user="me")[0], 503)
        self.assertEqual(self.req("/api/pick", user="me", body={"id": "owl"})[0], 503)

    def raw(self, method, path, headers=(), body=b""):
        c = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=5)
        c.putrequest(method, path)
        for k, v in headers:
            c.putheader(k, v)
        c.endheaders(body)
        r = c.getresponse()
        out = (r.status, r.read(), dict(r.getheaders()))
        c.close()
        return out

    def test_secret_required(self):
        self.start(FakeClient(self.users()), secret="s3cret")
        for path in ("/", "/index.html", "/api/state"):
            self.assertEqual(self.req(path, user="me")[0], 403, path)
            self.assertEqual(self.req(path, user="me", headers={"X-Picker-Secret": "bad"})[0], 403, path)
            self.assertEqual(self.req(path, headers={"X-Picker-Secret": "bad"})[0], 403, path)
        self.assertEqual(self.req("/api/pick", user="me", body={"id": "owl"})[0], 403)
        ok = {"X-Picker-Secret": "s3cret"}
        self.assertEqual(self.req("/", user="me", headers=ok)[0], 200)
        self.assertEqual(self.req("/api/state", user="me", headers=ok)[0], 200)
        self.assertEqual(self.req("/api/pick", user="me", body={"id": "owl"}, headers=ok)[0], 200)
        self.assertEqual(self.req("/healthz")[0], 200)
        self.assertEqual(self.req("/img/owl.png")[0], 200)

    def test_non_ascii_username(self):
        users = [{"pk": 1, "username": "jürg", "attributes": {}}]
        c = FakeClient(users); self.start(c)
        h = [("X-authentik-username", "jürg".encode("utf-8"))]
        h = [(k, v.decode("latin-1")) for k, v in h]
        code, body, _ = self.raw("GET", "/api/state", h)
        self.assertEqual(code, 200); self.assertEqual(json.loads(body)["user"], "jürg")
        payload = b'{"id": "owl"}'
        code, _, _ = self.raw("POST", "/api/pick", h + [("Content-Length", str(len(payload)))], payload)
        self.assertEqual(code, 200)
        self.assertEqual(c.writes[0][0], 1)

    def test_bad_content_length(self):
        self.start(FakeClient(self.users()))
        for v in ("-5", "99999", "abc"):
            code, _, _ = self.raw("POST", "/api/pick",
                                  [("X-authentik-username", "me"), ("Content-Length", v)])
            self.assertEqual(code, 400, v)

    def test_pick_merges_fresh_attributes(self):
        c = FakeClient(self.users()); self.start(c)
        orig = c.list_users
        def stale():
            r = orig()
            c.users[0]["attributes"]["added"] = "later"  # changes after the list
            return r
        c.list_users = stale
        self.assertEqual(self.req("/api/pick", user="me", body={"id": "owl"})[0], 200)
        self.assertEqual(c.writes[0][1].get("added"), "later")

    def test_head(self):
        self.start(FakeClient(self.users()))
        code, body, h = self.raw("HEAD", "/healthz")
        self.assertEqual((code, body), (200, b"")); self.assertEqual(h["Content-Length"], "2")
        code, body, h = self.raw("HEAD", "/img/owl.png")
        self.assertEqual((code, body), (200, b"")); self.assertEqual(h["Content-Type"], "image/png")
        self.assertGreater(int(h["Content-Length"]), 0)
        self.assertEqual(self.raw("HEAD", "/img/nope.png")[0], 404)

if __name__ == "__main__":
    unittest.main()
