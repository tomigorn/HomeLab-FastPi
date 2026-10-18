import io, json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from authentik_api import Client


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


if __name__ == "__main__":
    unittest.main()
