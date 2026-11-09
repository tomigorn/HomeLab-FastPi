"""Black-box tests for the picker container: HTTP only, against SUT (fixture app dir from run.sh) with MOCK as Authentik.

Classes run in name order and share one server: picks happen last (T6), the picked set is cached 30 s.
"""
import gzip
import http.client
import json
import os
import pathlib
import re
import socket
import unittest
import urllib.parse

SUT = os.environ["SUT"]
MOCK = os.environ["MOCK"]
APP = pathlib.Path(os.environ["APP"])
QUEUE = pathlib.Path(os.environ["QUEUE"])
SECRET = os.environ["SECRET"]
BASE = "https://sso.example.com/avatar-img"
THUMB_CACHE = "private, max-age=31536000, immutable"
TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


def req(path, method="GET", headers=None, body=None, base=SUT):
    u = urllib.parse.urlsplit(base)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=15)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, data


def raw(lines):
    u = urllib.parse.urlsplit(SUT)
    with socket.create_connection((u.hostname, u.port), timeout=15) as s:
        s.sendall(lines)
        data = b""
        while chunk := s.recv(65536):
            data += chunk
    return int(data.split(b" ", 2)[1])


def mock(path, body=None):
    if body is None:
        return json.loads(req(path, base=MOCK)[2])
    return req(path, "POST", {"Content-Type": "application/json"}, json.dumps(body), base=MOCK)


def picker(user="alice", **extra):
    h = {"X-Picker-Secret": SECRET}
    if user is not None:
        h["X-authentik-username"] = user
    h.update(extra)
    return h


def img(name):
    pack = "img-local" if name == "gamma" else "img"
    return (APP / pack / f"{name}.png").read_bytes()


def thumb(name):
    return (APP / "thumbs" / name).read_bytes()


class T1_Public(unittest.TestCase):
    def test_healthz(self):
        s, h, b = req("/healthz?probe=1")
        self.assertEqual((s, b, h["content-type"], h["cache-control"], h["x-content-type-options"]),
                         (200, b"ok", "text/plain; charset=utf-8", "no-store", "nosniff"))

    def test_head_healthz(self):
        s, h, b = req("/healthz", "HEAD")
        self.assertEqual((s, b, h["content-length"]), (200, b"", "2"))

    def test_icons(self):
        for path, ctype in [("/favicon.svg", "image/svg+xml"), ("/favicon-32.png", "image/png"),
                            ("/apple-touch-icon.png", "image/png")]:
            s, h, b = req(path)
            self.assertEqual((s, h["content-type"], h["cache-control"]), (200, ctype, "public, max-age=86400"), path)
            self.assertEqual(b, (APP / "static" / path[1:]).read_bytes())

    def test_unknown_get_404(self):
        for p in ("/nope", "/img/", "/img/alpha", "/static/index.html", "/app/server.py", "/gallery.json"):
            s, h, b = req(p)
            self.assertEqual((s, b, h["content-type"]), (404, b"not found", "text/plain; charset=utf-8"), p)

    def test_head_on_private_paths_404(self):
        for p in ("/", "/api/state", "/nope"):
            s, _, b = req(p, "HEAD", picker())
            self.assertEqual((s, b), (404, b""), p)

    def test_post_elsewhere_404(self):
        for p in ("/", "/api/state", "/api/pick/x", "/healthz"):
            s, _, b = req(p, "POST", picker(), b"{}")
            self.assertEqual((s, b), (404, b"not found"), p)

    def test_backfill_at_start(self):
        q = json.loads(QUEUE.read_text())
        self.assertEqual(set(q), {"alice", "carol"})
        self.assertEqual(q["alice"]["avatar"], "alpha")
        self.assertRegex(q["alice"]["at"], TS)
        self.assertEqual(q["carol"], {"avatar": "beta", "at": "2026-01-01T00:00:00Z"})


class T2_Images(unittest.TestCase):
    def test_lan_every_image(self):
        for name in ("alpha", "beta", "gamma", "a01"):
            s, h, b = req(f"/img/{name}.png", headers={"X-Avatar-Access": "lan"})
            self.assertEqual((s, h["content-type"], h["cache-control"], b), (200, "image/png", "public, max-age=86400", img(name)), name)

    def test_lan_unknown_or_missing_404(self):
        for name in ("zzz", "delta", "eps", "..%2Fgallery", "ALPHA"):
            s, _, b = req(f"/img/{name}.png", headers={"X-Avatar-Access": "lan"})
            self.assertEqual((s, b), (404, b"not found"), name)

    def test_secret_every_image_private(self):
        s, h, b = req("/img/gamma.png", headers={"X-Picker-Secret": SECRET})
        self.assertEqual((s, h["cache-control"], b), (200, "private, max-age=86400", img("gamma")))

    def test_secret_unknown_404(self):
        self.assertEqual(req("/img/zzz.png", headers={"X-Picker-Secret": SECRET})[:1], (404,))

    def test_gated_picked_public(self):
        for hdr in ({"X-Avatar-Access": "gated"}, {}, {"X-Avatar-Access": "LAN"}, {"X-Picker-Secret": "wrong"}):
            s, h, b = req("/img/alpha.png", headers=hdr)
            self.assertEqual((s, h["cache-control"], b), (200, "public, max-age=300", img("alpha")), hdr)

    def test_service_account_and_foreign_avatars_not_picked(self):
        for name in ("beta", "gamma"):
            s, _, b = req(f"/img/{name}.png", headers={"X-Avatar-Access": "gated"})
            self.assertEqual((s, b), (403, b"forbidden"), name)

    def test_gated_unpicked_needs_session(self):
        for cookie in ("", "authentik_session=nope", "authentik_session=redirect", "other=valid1",
                       "xauthentik_session=valid1"):
            s, _, b = req("/img/gamma.png", headers={"X-Avatar-Access": "gated", "Cookie": cookie})
            self.assertEqual((s, b), (403, b"forbidden"), cookie)

    def test_gated_unpicked_with_session(self):
        s, h, b = req("/img/gamma.png", headers={"X-Avatar-Access": "gated", "Cookie": "theme=x; authentik_session=valid1; y=z"})
        self.assertEqual((s, h["cache-control"], b), (200, "private, max-age=300", img("gamma")))

    def test_gated_unknown_without_session_403_with_session_404(self):
        self.assertEqual(req("/img/zzz.png", headers={"X-Avatar-Access": "gated"})[0], 403)
        self.assertEqual(req("/img/zzz.png", headers={"Cookie": "authentik_session=valid2"})[:3:2], (404, b"not found"))

    def test_session_answer_cached(self):
        mock("/_mock/clear-log", {})
        for _ in range(3):
            self.assertEqual(req("/img/a02.png", headers={"Cookie": "authentik_session=valid-cache"})[0], 200)
        self.assertEqual(mock("/_mock/state")["me_calls"], {"authentik_session=valid-cache": 1})

    def test_negative_session_not_cached(self):
        mock("/_mock/clear-log", {})
        for _ in range(2):
            self.assertEqual(req("/img/a02.png", headers={"Cookie": "authentik_session=bad-x"})[0], 403)
        self.assertEqual(mock("/_mock/state")["me_calls"], {"authentik_session=bad-x": 2})

    def test_session_check_error_503(self):
        s, _, b = req("/img/gamma.png", headers={"Cookie": "authentik_session=boom"})
        self.assertEqual((s, b), (503, b"Authentik unreachable"))

    def test_head_image(self):
        s, h, b = req("/img/alpha.png", "HEAD", {"X-Avatar-Access": "lan"})
        self.assertEqual((s, b, h["content-length"], h["content-type"]), (200, b"", str(len(img("alpha"))), "image/png"))


class T3_Thumbs(unittest.TestCase):
    def test_lan_and_secret_immutable(self):
        for hdr in ({"X-Avatar-Access": "lan"}, {"X-Picker-Secret": SECRET}):
            for name in ("gamma.abcdef0123.160.webp", "gamma.abcdef0123.320.webp"):
                s, h, b = req(f"/thumb/{name}", headers=hdr)
                self.assertEqual((s, h["content-type"], h["cache-control"], b), (200, "image/webp", THUMB_CACHE, thumb(name)), name)

    def test_picked_thumb_public(self):
        s, h, b = req("/thumb/alpha.0123456789.320.webp")
        self.assertEqual((s, h["cache-control"], b), (200, "public, max-age=300", thumb("alpha.0123456789.320.webp")))

    def test_unpicked_thumb_needs_session(self):
        self.assertEqual(req("/thumb/gamma.abcdef0123.160.webp")[:3:2], (403, b"forbidden"))
        s, h, _ = req("/thumb/gamma.abcdef0123.160.webp", headers={"Cookie": "authentik_session=valid3"})
        self.assertEqual((s, h["cache-control"]), (200, THUMB_CACHE))

    def test_bad_names_404(self):
        for name in ("gamma.ffffffffff.160.webp", "gamma.abcdef0123.640.webp", "beta.1111111111.160.webp",
                     "delta.2222222222.160.webp", "gamma.abcdef0123.160.png", "GAMMA.abcdef0123.160.webp",
                     "..%2Fthumbs.json", "thumbs.json", "gamma.abcdef012.160.webp"):
            s, _, b = req(f"/thumb/{name}", headers={"X-Avatar-Access": "lan"})
            self.assertEqual((s, b), (404, b"not found"), name)

    def test_bad_name_gated_unpicked_403(self):
        self.assertEqual(req("/thumb/gamma.ffffffffff.160.webp")[0], 403)

    def test_bad_name_of_picked_id_needs_session(self):
        self.assertEqual(req("/thumb/alpha.ffffffffff.160.webp")[0], 403)
        self.assertEqual(req("/thumb/alpha.ffffffffff.160.webp", headers={"Cookie": "authentik_session=valid4"})[0], 404)


class T4_Page(unittest.TestCase):
    def test_secret_required(self):
        for hdr in ({}, {"X-authentik-username": "alice"}, {"X-authentik-username": "alice", "X-Picker-Secret": SECRET + "x"},
                    {"X-authentik-username": "alice", "X-Picker-Secret": ""}):
            for p in ("/", "/index.html", "/api/state", "/api/whatever"):
                s, _, b = req(p, headers=hdr)
                self.assertEqual((s, b), (403, b"forbidden"), (p, hdr))
        s, _, b = req("/api/pick", "POST", {"X-authentik-username": "alice"}, b'{"id":"a03"}')
        self.assertEqual((s, b), (403, b"forbidden"))

    def test_login_required(self):
        for user in (None, "", "   "):
            for p in ("/", "/index.html"):
                s, _, b = req(p, headers=picker(user))
                self.assertEqual((s, b), (401, b"login required"), (p, user))

    def test_page(self):
        index = (APP / "static" / "index.html").read_bytes()
        for p in ("/", "/index.html", "/?x=1"):
            s, h, b = req(p, headers=picker())
            self.assertEqual((s, h["content-type"], h["cache-control"], h["vary"], b),
                             (200, "text/html; charset=utf-8", "no-store", "Accept-Encoding", index), p)
            self.assertNotIn("content-encoding", h)

    def test_page_gzip(self):
        s, h, b = req("/", headers=picker(**{"Accept-Encoding": "gzip, deflate"}))
        self.assertEqual((s, h["content-encoding"], h["content-length"]), (200, "gzip", str(len(b))))
        self.assertEqual(gzip.decompress(b), (APP / "static" / "index.html").read_bytes())

    def test_unknown_api_path_404(self):
        s, _, b = req("/api/nope", headers=picker())
        self.assertEqual((s, b), (404, b"not found"))


class T5_State(unittest.TestCase):
    def state(self, user):
        s, h, b = req("/api/state", headers=picker(user))
        self.assertEqual((s, h["content-type"], h["cache-control"]), (200, "application/json", "no-store"))
        return json.loads(b)

    def test_login_required_json(self):
        s, h, b = req("/api/state", headers=picker(None))
        self.assertEqual((s, h["content-type"], json.loads(b)), (401, "application/json", {"error": "login required"}))

    def test_state_shape(self):
        d = self.state("alice")
        self.assertEqual(list(d), ["user", "version", "groups", "avatars"])
        self.assertEqual((d["user"], d["version"]), ("alice", "9.9.9-test"))
        self.assertEqual(d["groups"], [{"id": "g1", "label": "Group one"}, {"id": "g2", "label": "Group two"}])
        ids = [a["id"] for a in d["avatars"]]
        self.assertEqual(ids, ["alpha", "beta", "gamma"] + [f"a{i:02d}" for i in range(1, 11)])
        alpha = d["avatars"][0]
        self.assertEqual(alpha, {"id": "alpha", "name": "Alpha", "url": f"{BASE}/img/alpha.png", "color": "#111111",
                                 "group": "g1", "status": "mine", "thumb": "thumb/alpha.0123456789"})
        self.assertEqual(d["avatars"][2]["thumb"], "thumb/gamma.abcdef0123")
        self.assertEqual(d["avatars"][1]["thumb"], "thumb/beta.1111111111")
        self.assertNotIn("thumb", d["avatars"][3])
        self.assertIsNone(d["avatars"][-1]["group"])

    def test_status_never_reveals_holder(self):
        d = self.state("bob")
        st = {a["id"]: a["status"] for a in d["avatars"]}
        self.assertEqual((st["alpha"], st["beta"], st["gamma"], st["a01"]), ("taken", "free", "free", "free"))
        self.assertNotIn("alice", json.dumps(d))

    def test_utf8_username(self):
        u = urllib.parse.urlsplit(SUT)
        c = http.client.HTTPConnection(u.hostname, u.port, timeout=15)
        c.putrequest("GET", "/api/state")
        c.putheader("X-Picker-Secret", SECRET)
        c.putheader("X-authentik-username", "jörg".encode())
        c.endheaders()
        r = c.getresponse()
        d = json.loads(r.read())
        c.close()
        self.assertEqual((r.status, d["user"]), (200, "jörg"))

    def test_username_trimmed(self):
        self.assertEqual(self.state("  alice  ")["user"], "alice")

    def test_gzip(self):
        s, h, b = req("/api/state", headers=picker(**{"Accept-Encoding": "gzip"}))
        self.assertEqual((s, h["content-encoding"], h["vary"]), (200, "gzip", "Accept-Encoding"))
        self.assertEqual(json.loads(gzip.decompress(b))["user"], "alice")

    def test_authentik_down_503(self):
        mock("/_mock/fail", ["list"])
        try:
            s, h, b = req("/api/state", headers=picker())
            self.assertEqual((s, h["content-type"], json.loads(b)), (503, "application/json", {"error": "Authentik unreachable"}))
        finally:
            mock("/_mock/fail", [])

    def test_pagination_reads_every_page(self):
        mock("/_mock/clear-log", {})
        self.state("alice")
        pages = [p for m, p, *_ in mock("/_mock/state")["log"] if m == "GET"]
        self.assertEqual(pages, [f"/api/v3/core/users/?page={i}&page_size=100" for i in (1, 2, 3)])


class T6_Pick(unittest.TestCase):
    def pick(self, user, body, **hdr):
        h = picker(user, **{"Content-Type": "application/json"})
        h.update(hdr)
        s, hh, b = req("/api/pick", "POST", h, body if isinstance(body, bytes) else json.dumps(body))
        return s, hh, json.loads(b) if hh.get("content-type") == "application/json" else b

    def test_a_validation(self):
        for body, want in [(b"not json", "unknown avatar"), (b"[1]", "unknown avatar"), ({"id": 5}, "unknown avatar"),
                           ({"id": "zzz"}, "unknown avatar"), ({"id": "delta"}, "unknown avatar"), ({}, "unknown avatar"),
                           (b"", "unknown avatar"), (b"null", "unknown avatar")]:
            s, _, d = self.pick("bob", body)
            self.assertEqual((s, d), (400, {"error": want}), body)
        s, _, d = self.pick("bob", b'{"id":"' + b"x" * 1100 + b'"}')
        self.assertEqual((s, d), (400, {"error": "bad request"}))

    def test_a_bad_content_length(self):
        for cl in (b"-1", b"abc"):
            self.assertEqual(raw(b"POST /api/pick HTTP/1.1\r\nHost: x\r\nConnection: close\r\nX-Picker-Secret: " + SECRET.encode()
                                 + b"\r\nX-authentik-username: bob\r\nContent-Length: " + cl + b"\r\n\r\n"), 400, cl)

    def test_a_login_required(self):
        s, _, d = self.pick(None, {"id": "a03"})
        self.assertEqual((s, d), (401, {"error": "login required"}))

    def test_b_taken(self):
        s, _, d = self.pick("bob", {"id": "alpha"})
        self.assertEqual((s, d), (409, {"error": "just taken - pick another"}))

    def test_b_unknown_user(self):
        for user in ("mallory", "svc-bot", "Alice"):
            s, _, d = self.pick(user, {"id": "a05"})
            self.assertEqual((s, d), (403, {"error": "unknown user"}), user)

    def test_c_authentik_down(self):
        for fail in ("list", "patch"):
            mock("/_mock/fail", [fail])
            try:
                s, _, d = self.pick("bob", {"id": "a06"})
                self.assertEqual((s, d), (503, {"error": "Authentik unreachable"}), fail)
            finally:
                mock("/_mock/fail", [])
        self.assertNotIn("bob", json.loads(QUEUE.read_text()))

    def test_d_pick(self):
        self.assertEqual(req("/img/beta.png", headers={"X-Avatar-Access": "gated"})[0], 403)
        mock("/_mock/clear-log", {})
        s, h, d = self.pick("bob", {"id": "beta"})
        self.assertEqual((s, h["content-type"], d), (200, "application/json", {"ok": True, "url": f"{BASE}/img/beta.png"}))
        patches = [e for e in mock("/_mock/state")["log"] if e[0] == "PATCH"]
        self.assertEqual(patches, [["PATCH", "/api/v3/core/users/2/", {"attributes": {"theme": "dark", "avatar": f"{BASE}/img/beta.png"}}]])
        q = json.loads(QUEUE.read_text())
        self.assertEqual(q["bob"]["avatar"], "beta")
        self.assertRegex(q["bob"]["at"], TS)
        self.assertEqual(QUEUE.read_text(), json.dumps(q, indent=1, sort_keys=True) + "\n")
        self.assertEqual(QUEUE.stat().st_mode & 0o777, 0o644)
        self.assertFalse(QUEUE.with_name(QUEUE.name + ".tmp").exists())
        s, h, b = req("/img/beta.png", headers={"X-Avatar-Access": "gated"})
        self.assertEqual((s, h["cache-control"]), (200, "public, max-age=300"))

    def test_e_repick_own_and_null_attributes(self):
        s, _, d = self.pick("alice", {"id": "alpha"})
        self.assertEqual((s, d["ok"]), (200, True))
        s, _, d = self.pick("carol", {"id": "a07", "extra": 1})
        self.assertEqual(s, 200)
        carol = next(u for u in mock("/_mock/state")["users"] if u["username"] == "carol")
        self.assertEqual(carol["attributes"], {"avatar": f"{BASE}/img/a07.png"})
        self.assertEqual(json.loads(QUEUE.read_text())["carol"]["avatar"], "a07")

    def test_e_utf8_user_queue_format(self):
        h = picker(None, **{"Content-Type": "application/json"})
        u = urllib.parse.urlsplit(SUT)
        c = http.client.HTTPConnection(u.hostname, u.port, timeout=15)
        c.putrequest("POST", "/api/pick")
        for k, v in h.items():
            c.putheader(k, v)
        c.putheader("X-authentik-username", "jörg".encode())
        c.putheader("Content-Length", "13")
        c.endheaders(b'{"id":"a09"}\n')
        r = c.getresponse()
        r.read()
        c.close()
        self.assertEqual(r.status, 200)
        text = QUEUE.read_text()
        q = json.loads(text)
        self.assertEqual(q["jörg"]["avatar"], "a09")
        self.assertEqual(text, json.dumps(q, indent=1, sort_keys=True) + "\n")
        self.assertIn("j\\u00f6rg", text)

    def test_f_switch_frees_old(self):
        s, _, _ = self.pick("bob", {"id": "a08"})
        self.assertEqual(s, 200)
        st = {a["id"]: a["status"] for a in json.loads(req("/api/state", headers=picker("alice"))[2])["avatars"]}
        self.assertEqual((st["beta"], st["a08"]), ("free", "taken"))
        self.assertEqual(req("/img/beta.png", headers={"X-Avatar-Access": "gated"})[0], 403)


if __name__ == "__main__":
    unittest.main()
