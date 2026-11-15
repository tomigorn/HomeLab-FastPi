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

    def test_no_overlapping_dots(self):
        """Owner 2026-11-15: no two dots may overlap. Positions are computed at build time and baked into the app bundle."""
        bundle = "".join(f.read_text(encoding="utf-8", errors="ignore") for f in self.out.rglob("_app-*.js"))
        size = int(re.search(r'"blipSize":(\d+)', bundle).group(1))
        dots = [(m.group(1), int(m.group(2)), int(m.group(3))) for m in re.finditer(r'"id":"([^"]+)"[^{}]*?"position":\[(-?\d+),(-?\d+)\]', bundle)]
        self.assertGreaterEqual(len(dots), len(list(items())))
        close = [(a[0], b[0], round(((a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5, 1)) for i, a in enumerate(dots) for b in dots[i + 1:]
                 if ((a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5 < size]
        self.assertEqual(close, [], f"dots closer than {size} px")


if __name__ == "__main__":
    unittest.main()
