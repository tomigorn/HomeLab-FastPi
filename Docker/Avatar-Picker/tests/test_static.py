"""Static checks of the single-file picker page (app/static/index.html).

Independent of the gallery contents: only the page's own markup/script is inspected.
"""
import pathlib, re, unittest
from html.parser import HTMLParser

PAGE = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "index.html"


class _Collect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []  # (tag, attrs dict)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class StaticPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")
        p = _Collect()
        p.feed(cls.html)
        cls.tags = p.tags
        m = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", cls.html, re.S)
        cls.js = "\n".join(m)

    def find(self, tag, **attrs):
        return [a for t, a in self.tags
                if t == tag and all(a.get(k.replace("_", "-")) == v for k, v in attrs.items())]

    def test_basic_document(self):
        self.assertTrue(self.html.lower().startswith("<!doctype html>"))
        self.assertTrue(self.find("meta", name="viewport"))
        self.assertTrue(self.find("html", lang="en"))

    def test_category_nav_with_aria_label(self):
        self.assertEqual(len(self.find("nav", aria_label="Categories")), 1)
        self.assertIn("aria-current", self.js)
        self.assertIn("IntersectionObserver", self.js)

    def test_sections_get_group_id(self):
        self.assertRegex(self.js, r"\.id\s*=\s*grp\.id")
        self.assertIn("location.hash", self.js)
        self.assertIn("scroll-margin-top", self.html)

    def test_reduced_motion_respected(self):
        self.assertIn("prefers-reduced-motion", self.html)

    def test_search_input_has_label(self):
        inputs = [a for a in self.find("input") if a.get("type") == "search"]
        self.assertEqual(len(inputs), 1)
        sid = inputs[0].get("id")
        self.assertTrue(sid)
        labelled = self.find("label", **{"for": sid}) or inputs[0].get("aria-label")
        self.assertTrue(labelled)
        self.assertIn("normalize(\"NFD\")", self.js.replace("'", '"'))
        self.assertIn("Escape", self.js)
        self.assertIn("No avatars match", self.html)

    def test_lazy_images(self):
        for attr in ('loading="lazy"', 'decoding="async"', 'width="512"', 'height="512"'):
            self.assertIn(attr, self.html)

    def test_buttons_present(self):
        self.assertTrue(self.find("button", id="ui-top"), "back-to-top button")
        self.assertTrue(self.find("button", id="ui-surprise"), "surprise button")
        self.assertIn("Back to top", self.html)
        self.assertIn("Surprise me", self.html)
        self.assertIn("No avatar yet", self.html)

    def test_surprise_never_picks(self):
        body = re.search(r"function surprise\(\)\s*\{(.*?)\n\}", self.js, re.S)
        self.assertIsNotNone(body, "surprise() function")
        self.assertNotIn("pick(", body.group(1))
        self.assertNotIn(".click(", body.group(1))

    def test_taken_marking_kept(self):
        self.assertIn(" · taken", self.js)
        self.assertRegex(self.js, r"disabled\s*=\s*a\.status\s*===\s*\"taken\"")

    def test_api_calls_kept(self):
        self.assertIn('fetch("api/state"', self.js)
        self.assertIn('fetch("api/pick"', self.js)

    def test_no_external_resources(self):
        for t, a in self.tags:
            for k in ("src", "href"):
                v = a.get(k) or ""
                if t in ("script", "link", "img", "iframe"):
                    self.assertNotRegex(v, r"^(https?:)?//", f"external {t} {k}={v}")
        self.assertNotRegex(self.html, r"@import|url\(\s*['\"]?(https?:)?//")

    def test_ids_unique(self):
        ids = [a["id"] for _, a in self.tags if "id" in a]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
