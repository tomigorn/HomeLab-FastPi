import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUADRANTS = {"languages", "hardware", "devops", "services"}
RINGS = {"production", "daily", "learning", "retired"}
TAGS = {"fastpi", "beefy", "tower", "security", "media", "network", "sso", "monitoring", "device", "dev"}
IPV4 = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b")
MAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def parse(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    assert m, f"{path}: no front matter"
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return text, meta, m.group(2)


def items():
    return sorted((ROOT / "radar").glob("**/*.md"))


class ContentTest(unittest.TestCase):
    def test_items_exist(self):
        self.assertTrue(items())

    def test_items(self):
        for p in items():
            with self.subTest(item=str(p.relative_to(ROOT))):
                text, meta, body = parse(p)
                self.assertTrue(meta.get("title"))
                self.assertIn(meta.get("ring"), RINGS)
                self.assertIn(meta.get("quadrant"), QUADRANTS)
                tags = meta.get("tags", "")
                self.assertTrue(tags.startswith("[") and tags.endswith("]"), "tags must be a flow list")
                for t in [x.strip() for x in tags[1:-1].split(",") if x.strip()]:
                    self.assertIn(t, TAGS)
                self.assertTrue([l for l in body.splitlines() if l.strip()])
                self.assertIsNone(IPV4.search(text))
                self.assertIsNone(MAIL.search(text))

    def test_required_items(self):
        required = {
            "languages": ["rust", "python", "bash"],
            "hardware": ["fastpi", "beefy", "tower", "bazzite-pc", "macbook", "bambu-lab", "sony-tv", "apple-tv"],
            "devops": ["docker", "cup", "security-monitoring", "wake-on-lan"],
            "services": ["traefik", "cloudflare", "authentik", "wireguard", "godaddy", "no-ip", "duckdns", "crowdsec", "adguard", "jellyfin"],
        }
        found = {p.stem: parse(p)[1].get("quadrant") for p in items()}
        for quadrant, ids in required.items():
            for i in ids:
                with self.subTest(item=i):
                    self.assertEqual(found.get(i), quadrant)
        self.assertGreaterEqual(len(found), 40)
        self.assertLessEqual(len(found), 60)

    def test_no_ldaps_item(self):
        self.assertFalse(list((ROOT / "radar").glob("**/ldaps.md")))
        text = (ROOT / "radar/2026-11-12/authentik.md").read_text(encoding="utf-8")
        self.assertIn("OIDC/OAuth2", text)

    def test_config(self):
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        self.assertEqual({q["id"] for q in cfg["quadrants"]}, QUADRANTS)
        self.assertEqual({r["id"] for r in cfg["rings"]}, RINGS)
        self.assertEqual(cfg["basePath"], "/")
        self.assertFalse(cfg.get("jsFile"))
        self.assertFalse(cfg.get("social"))
        self.assertFalse(cfg.get("imprint"))
        self.assertFalse(cfg.get("editUrl"))


def version(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


class BuilderTreeTest(unittest.TestCase):
    def test_builder_tree_uses_patched_versions(self):
        manifest = json.loads((ROOT / "builder-package.json").read_text())
        lock = json.loads((ROOT / "builder-lock.json").read_text())["packages"]
        self.assertEqual(lock[""].get("devDependencies"), manifest.get("devDependencies"))
        self.assertGreaterEqual(version(lock["node_modules/next"]["version"]), (15, 5, 29))
        for key, entry in lock.items():
            if key.endswith("node_modules/postcss"):
                self.assertGreaterEqual(version(entry["version"]), (8, 5, 32), key)
            if key.endswith("typescript-estree/node_modules/minimatch"):
                self.assertGreaterEqual(version(entry["version"]), (11, 0, 1), key)


if __name__ == "__main__":
    unittest.main()
