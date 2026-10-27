"""Static checks of the single-file picker page (app/static/index.html).

Independent of the gallery contents: only the page's own markup/script is inspected.
"""
import pathlib, re, struct, unittest
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

    def test_favicons_linked(self):
        """The tab shows the picker's own icon (SVG + PNG fallback + Apple touch icon)."""
        icons = {a.get("href"): a for a in self.find("link") if "icon" in (a.get("rel") or "")}
        self.assertEqual(icons["favicon.svg"].get("type"), "image/svg+xml")
        self.assertEqual(icons["favicon-32.png"].get("sizes"), "32x32")
        self.assertEqual(icons["apple-touch-icon.png"].get("rel"), "apple-touch-icon")
        self.assertNotIn("data:,", icons)
        static = PAGE.parent
        self.assertTrue(static.joinpath("favicon.svg").read_text().lstrip().startswith("<svg"))
        for name, size in (("favicon-32.png", 32), ("apple-touch-icon.png", 180)):
            head = static.joinpath(name).read_bytes()[:24]
            self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n", name)
            self.assertEqual(struct.unpack(">II", head[16:24]), (size, size), name)

    def test_ids_unique(self):
        ids = [a["id"] for _, a in self.tags if "id" in a]
        self.assertEqual(len(ids), len(set(ids)))

    def css_rule(self, selector):
        m = re.search(r"(?:^|[}\s])" + re.escape(selector) + r"\{([^}]*)\}", self.html)
        self.assertIsNotNone(m, selector)
        return m.group(1)

    def test_captions_hyphenate_instead_of_breaking_mid_word(self):
        name = self.css_rule(".name")
        self.assertIn("hyphens:auto", name)
        self.assertIn("-webkit-hyphens:auto", name)
        self.assertIn("overflow-wrap:break-word", name)
        self.assertNotIn("anywhere", name)
        self.assertIn("min-height:2.5em", name)
        self.assertIn("line-height:1.25", name)

    def test_tiles_align_to_the_top_of_their_row(self):
        self.assertIn("align-items:start", self.css_rule(".grid"))

    def test_long_words_get_soft_hyphens_in_the_caption_only(self):
        self.assertIn('querySelector(".name").textContent = hyphenate(', self.js)
        self.assertIn("\\u00ad", self.js)


if __name__ == "__main__":
    unittest.main()
