#!/usr/bin/env python3
"""Tests for lt-token.py. Run: python3 test_lt_token.py"""
import importlib.util
import os
import re
import tempfile
import unittest
from pathlib import Path

BASE = """http:
  routers:
    languagetool-token-Anna-Laptop:
      rule: "Host(`lang-tool.ddns.net`) && PathPrefix(`/lt-aaaa`)"
      entryPoints: ["langtool"]
      priority: 5
      service: languagetool
      middlewares:
        - languagetool-token-strip-Anna-Laptop
        - languagetool-secure-headers
      tls:
        certResolver: le

  middlewares:
    languagetool-token-strip-Anna-Laptop:
      replacePathRegex:
        regex: "^/lt-aaaa/(?:api/)?(?:v2/)?(.*)"
        replacement: "/v2/$1"
"""


def load(path):
    os.environ["LT_TOKEN_FILE"] = str(path)
    os.environ["LT_BACKUP_DIR"] = str(path.parent / "backups")
    spec = importlib.util.spec_from_file_location("lt", Path(__file__).parent / "lt-token.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LtToken(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.file = Path(self.dir.name) / "languagetool-token.yml"
        self.file.write_text(BASE)
        self.file.chmod(0o640)
        self.lt = load(self.file)

    def tearDown(self):
        self.dir.cleanup()

    def test_add_prints_url_and_adds_router_and_middleware(self):
        url = self.lt.add("Filip-LinuxLaptop")
        m = re.fullmatch(r"https://lang-tool\.ddns\.net/lt-([0-9a-f]{64})", url)
        self.assertTrue(m)
        text = self.file.read_text()
        self.assertEqual(self.lt.labels(text), ["Anna-Laptop", "Filip-LinuxLaptop"])
        self.assertIn(f"PathPrefix(`/lt-{m.group(1)}`)", text)
        self.assertIn(f'regex: "^/lt-{m.group(1)}/', text)
        self.assertLess(text.index("languagetool-token-Filip-LinuxLaptop:"), text.index("\n  middlewares:\n"))
        self.assertGreater(text.index("languagetool-token-strip-Filip-LinuxLaptop:"), text.index("\n  middlewares:\n"))

    def test_add_keeps_permissions_and_writes_private_backup(self):
        self.lt.add("Filip-LinuxLaptop")
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o640)
        self.assertEqual(sorted(p.name for p in Path(self.dir.name).iterdir()), ["backups", "languagetool-token.yml"])
        baks = list((Path(self.dir.name) / "backups").glob("languagetool-token.yml.*"))
        self.assertEqual(len(baks), 1)
        self.assertEqual(baks[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(baks[0].read_text(), BASE)

    def test_tokens_are_unique(self):
        a = self.lt.add("Filip-LinuxLaptop")
        b = self.lt.add("Filip-Phone")
        self.assertNotEqual(a, b)

    def test_duplicate_and_bad_labels_are_refused(self):
        for bad in ["Anna-Laptop", "filip", "Filip Laptop", "Filip-", "../x-y"]:
            with self.assertRaises(SystemExit, msg=bad):
                self.lt.add(bad)
        self.assertEqual(self.file.read_text(), BASE)

    def test_list_never_shows_tokens(self):
        self.lt.add("Filip-LinuxLaptop")
        self.assertEqual(self.lt.labels(self.file.read_text()), ["Anna-Laptop", "Filip-LinuxLaptop"])

    def test_remove_deletes_both_blocks_only(self):
        self.lt.add("Filip-LinuxLaptop")
        self.lt.remove("Filip-LinuxLaptop")
        text = self.file.read_text()
        self.assertNotIn("Filip", text)
        self.assertEqual(self.lt.labels(text), ["Anna-Laptop"])
        self.assertIn("languagetool-token-strip-Anna-Laptop:", text)
        with self.assertRaises(SystemExit):
            self.lt.remove("Nobody-Here")


if __name__ == "__main__":
    unittest.main()
