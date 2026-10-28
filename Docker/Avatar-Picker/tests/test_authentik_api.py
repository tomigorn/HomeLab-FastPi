import io, json, os, sys, unittest, urllib.error, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from authentik_api import AuthentikError, Client


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def opener_for(pages):
    calls = []
    def opener(req, timeout=None):
        calls.append(req.full_url)
        return Resp(json.dumps(pages(len(calls))).encode())
    opener.calls = calls
    return opener


class PaginationTest(unittest.TestCase):
    def test_follows_pages(self):
        def pages(n):
            return {"results": [{"pk": n, "type": "internal"}],
                    "pagination": {"next": n + 1 if n < 3 else 0}}
        o = opener_for(pages)
        self.assertEqual([u["pk"] for u in Client("http://a", "t", opener=o).list_users()], [1, 2, 3])

    def test_stops_on_non_advancing_next(self):
        o = opener_for(lambda n: {"results": [], "pagination": {"next": 1}})
        Client("http://a", "t", opener=o).list_users()
        self.assertEqual(len(o.calls), 1)

    def test_caps_pages(self):
        o = opener_for(lambda n: {"results": [], "pagination": {"next": n + 1}})
        Client("http://a", "t", opener=o).list_users()
        self.assertEqual(len(o.calls), 100)

    def test_get_user(self):
        o = opener_for(lambda n: {"pk": 7, "attributes": {"a": 1}})
        self.assertEqual(Client("http://a", "t", opener=o).get_user(7)["pk"], 7)
        self.assertTrue(o.calls[0].endswith("/api/v3/core/users/7/"))


class SessionTest(unittest.TestCase):
    def opener(self, status):
        calls = []
        def o(req, timeout=None):
            calls.append(req)
            if isinstance(status, Exception):
                raise status
            if status != 200:
                raise urllib.error.HTTPError(req.full_url, status, "x", {}, io.BytesIO(b"{}"))
            return Resp(b'{"user": {}}')
        o.calls = calls
        return o

    def test_valid_session_sends_only_the_cookie(self):
        o = self.opener(200)
        self.assertTrue(Client("http://a", "tok", session_opener=o).session_valid("abc"))
        req = o.calls[0]
        self.assertEqual(req.full_url, "http://a/api/v3/core/users/me/")
        self.assertEqual(req.get_header("Cookie"), "authentik_session=abc")
        self.assertIsNone(req.get_header("Authorization"))

    def test_no_session(self):
        for code in (401, 403, 302):
            self.assertFalse(Client("http://a", "t", session_opener=self.opener(code)).session_valid("abc"), code)

    def test_empty_cookie_never_asks(self):
        o = self.opener(200)
        self.assertFalse(Client("http://a", "t", session_opener=o).session_valid(""))
        self.assertEqual(o.calls, [])

    def test_unreachable_raises(self):
        for err in (500, OSError("down")):
            with self.assertRaises(AuthentikError):
                Client("http://a", "t", session_opener=self.opener(err)).session_valid("abc")

    def test_default_opener_does_not_follow_redirects(self):
        import authentik_api
        h = [x for x in authentik_api._session_opener.handlers if isinstance(x, urllib.request.HTTPRedirectHandler)]
        self.assertTrue(h and all(type(x) is not urllib.request.HTTPRedirectHandler for x in h))


if __name__ == "__main__":
    unittest.main()
