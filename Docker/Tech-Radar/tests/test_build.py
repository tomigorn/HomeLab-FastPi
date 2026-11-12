import os
import re
import unittest
from pathlib import Path

from test_content import items, parse

BUILD = os.environ.get("TECH_RADAR_BUILD_DIR")
EXT = re.compile(r"""<(?:script|link|img)\b[^>]*?\b(?:src|href)\s*=\s*["']?(?:https?:)?//""", re.I)
JS_LOAD = re.compile(r"""(?:\.src\s*=|\bimport\s*\(|importScripts\s*\(|fetch\s*\()\s*["'`]https?://""")
CSS_URL = re.compile(r"""url\(\s*["']?(?:https?:)?//""", re.I)


@unittest.skipUnless(BUILD, "TECH_RADAR_BUILD_DIR not set")
class BuildTest(unittest.TestCase):
    def setUp(self):
        self.out = Path(BUILD)

    def test_index(self):
        self.assertTrue((self.out / "index.html").is_file())

    def test_item_pages(self):
        for p in items():
            _, meta, _ = parse(p)
            q, i = meta["quadrant"], p.stem
            with self.subTest(item=f"{q}/{i}"):
                self.assertTrue((self.out / q / i / "index.html").is_file() or (self.out / q / f"{i}.html").is_file())

    def test_no_third_party(self):
        for f in self.out.rglob("*"):
            if f.suffix not in (".html", ".js", ".css"):
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            with self.subTest(file=str(f.relative_to(self.out))):
                if f.suffix == ".html":
                    self.assertIsNone(EXT.search(text))
                if f.suffix == ".js":
                    self.assertIsNone(JS_LOAD.search(text))
                if f.suffix in (".css", ".html"):
                    self.assertIsNone(CSS_URL.search(text))


if __name__ == "__main__":
    unittest.main()
