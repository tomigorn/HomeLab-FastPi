"""Black-box tests: HTTP only, against BASE (photo fixture from run.sh) and BASE_EMPTY (empty photo dir)."""
import http.client
import json
import os
import pathlib
import unittest
import urllib.parse

BASE = os.environ["BASE"]
BASE_EMPTY = os.environ["BASE_EMPTY"]
PHOTOS = pathlib.Path(os.environ["PHOTOS"])
LISTED = ["a.jpg", "b.PNG", "c.webp", "d.jpeg", "e.bmp", "f.gif", "g h.jpg", "outside.jpg"]


def req(path, base=BASE, method="GET", headers=None):
    u = urllib.parse.urlsplit(base)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    c.request(method, path, headers=headers or {})
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, body


class ListPhotos(unittest.TestCase):
    def test_lists_images_sorted_with_urls_from_host_header(self):
        s, h, b = req("/", headers={"Host": "backdrop-carousel.example.com"})
        self.assertEqual(s, 200)
        self.assertEqual(h["content-type"], "application/json")
        self.assertEqual(json.loads(b), [{"name": n, "url": f"http://backdrop-carousel.example.com/photo/{n}"}
                                         for n in sorted(LISTED)])

    def test_compact_json(self):
        _, _, b = req("/", headers={"Host": "h"})
        self.assertTrue(b.startswith(b'[{"name":"a.jpg","url":"http://h/photo/a.jpg"},'))

    def test_empty_dir_lists_nothing(self):
        s, _, b = req("/", base=BASE_EMPTY)
        self.assertEqual((s, json.loads(b)), (200, []))

    def test_query_string_ignored(self):
        s, _, b = req("/?x=1", headers={"Host": "h"})
        self.assertEqual(s, 200)
        self.assertEqual(len(json.loads(b)), len(LISTED))


class Photo(unittest.TestCase):
    def check_file(self, name, ctype):
        s, h, b = req(f"/photo/{name}")
        self.assertEqual(s, 200, name)
        self.assertEqual(h["content-type"], ctype)
        self.assertEqual(b, (PHOTOS / name).read_bytes())
        self.assertEqual(h["content-length"], str(len(b)))
        self.assertEqual(h["accept-ranges"], "bytes")
        self.assertIn("last-modified", h)
        self.assertIn("etag", h)

    def test_media_types(self):
        for name, ctype in [("a.jpg", "image/jpeg"), ("b.PNG", "image/png"), ("c.webp", "image/webp"),
                            ("d.jpeg", "image/jpeg"), ("e.bmp", "image/bmp"), ("f.gif", "image/gif")]:
            self.check_file(name, ctype)

    def test_not_found_json(self):
        for name in ("missing.jpg", "notes.txt", "sub", "outside.jpg"):
            s, h, b = req(f"/photo/{name}")
            self.assertEqual((s, h["content-type"], json.loads(b)), (404, "application/json", {"error": "not found"}), name)

    def test_traversal_refused(self):
        for path in ("/photo/..%2F..%2Fetc%2Fpasswd", "/photo/%2E%2E%2Fsecret.jpg", "/photo/sub/inner.jpg",
                     "/photo/../secret.jpg", "/photo/..%5Csecret.jpg"):
            s, _, b = req(path)
            self.assertEqual(s, 404, path)
            self.assertNotIn(b"TOPSECRET", b)

    def test_url_encoded_name(self):
        s, _, b = req("/photo/a%2Ejpg")
        self.assertEqual((s, b), (200, (PHOTOS / "a.jpg").read_bytes()))

    def test_space_in_name(self):
        s, h, b = req("/photo/g%20h.jpg")
        self.assertEqual((s, h["content-type"], b), (200, "image/jpeg", (PHOTOS / "g h.jpg").read_bytes()))

    def test_range_request(self):
        s, h, b = req("/photo/a.jpg", headers={"Range": "bytes=0-9"})
        full = (PHOTOS / "a.jpg").read_bytes()
        self.assertEqual(s, 206)
        self.assertEqual(b, full[:10])
        self.assertEqual(h["content-range"], f"bytes 0-9/{len(full)}")

    def test_suffix_range(self):
        s, h, b = req("/photo/c.webp", headers={"Range": "bytes=-5"})
        full = (PHOTOS / "c.webp").read_bytes()
        self.assertEqual((s, b, h["content-range"]), (206, full[-5:], f"bytes {len(full) - 5}-{len(full) - 1}/{len(full)}"))

    def test_etag_stable(self):
        e1 = req("/photo/a.jpg")[1]["etag"]
        e2 = req("/photo/a.jpg")[1]["etag"]
        self.assertEqual(e1, e2)
        self.assertNotEqual(e1, req("/photo/c.webp")[1]["etag"])


class Random(unittest.TestCase):
    def test_returns_one_of_the_listed_photos(self):
        files = {(PHOTOS / n).read_bytes(): n for n in LISTED if n != "outside.jpg"}
        files[(PHOTOS / "outside.jpg").read_bytes()] = "outside.jpg"
        seen = set()
        for _ in range(60):
            s, h, b = req("/random")
            self.assertEqual(s, 200)
            self.assertIn(b, files)
            seen.add(files[b])
            self.assertTrue(h["content-type"].startswith("image/"))
        self.assertGreaterEqual(len(seen), 3)

    def test_empty_dir_404(self):
        s, h, b = req("/random", base=BASE_EMPTY)
        self.assertEqual((s, h["content-type"], json.loads(b)), (404, "application/json", {"error": "no photos available"}))


class Routing(unittest.TestCase):
    def test_unknown_path_404(self):
        for p in ("/nope", "/photo", "/photo/", "/random/x"):
            s, h, b = req(p)
            self.assertEqual((s, h["content-type"], json.loads(b)), (404, "application/json", {"detail": "Not Found"}), p)

    def test_post_405(self):
        for p in ("/", "/random", "/photo/a.jpg"):
            s, h, b = req(p, method="POST")
            self.assertEqual((s, h.get("allow"), json.loads(b)), (405, "GET", {"detail": "Method Not Allowed"}), p)

    def test_new_photo_seen_without_restart(self):
        p = PHOTOS / "zz-new.jpg"
        p.write_bytes(b"\xff\xd8new")
        try:
            names = [x["name"] for x in json.loads(req("/", headers={"Host": "h"})[2])]
            self.assertIn("zz-new.jpg", names)
            self.assertEqual(req("/photo/zz-new.jpg")[2], b"\xff\xd8new")
        finally:
            p.unlink()


if __name__ == "__main__":
    unittest.main()
