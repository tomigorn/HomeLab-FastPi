#!/usr/bin/env python3
"""Tests for the VPN hint on the SSO app page. python3 test_vpn_tiles.py"""
import glob
import json
import os
import re
import subprocess
import unittest
from pathlib import Path

import yaml

AUTHENTIK = Path(__file__).resolve().parent.parent
TEMPLATES = Path(os.environ.get("VPN_TILES_TEMPLATES", AUTHENTIK / "custom-templates"))
JS = TEMPLATES / "holy-grail" / "vpn-tiles.js"
TEMPLATE = TEMPLATES / "if" / "user.html"
DYNAMIC = AUTHENTIK.parent / "Traefik" / "traefik" / "dynamic"


def local_only_hosts() -> set[str]:
    local, public = set(), set()
    for f in glob.glob(str(DYNAMIC / "*.yml")):
        routers = ((yaml.safe_load(open(f)) or {}).get("http") or {}).get("routers") or {}
        for r in routers.values():
            rule = r.get("rule", "")
            if "Path" in rule:
                continue
            target = local if "local-networks@file" in (r.get("middlewares") or []) else public
            target.update(re.findall(r"Host\(`([a-z0-9-]+)\.holy-grail\.ch`\)", rule))
    return local - public


def call(fn: str, *args):
    code = f"const m=require({json.dumps(str(JS))});console.log(JSON.stringify(m.{fn}(...{json.dumps(args)})))"
    return json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)


class Hosts(unittest.TestCase):
    def test_list_matches_the_traefik_routes(self):
        listed = set(call("localOnlyHosts"))
        self.assertEqual(listed, local_only_hosts())

    def test_known_examples(self):
        self.assertTrue(call("isLocalOnly", "https://grafana.holy-grail.ch"))
        self.assertTrue(call("isLocalOnly", "https://traefik.holy-grail.ch/dashboard/"))
        self.assertFalse(call("isLocalOnly", "https://jellyfin.holy-grail.ch"))

    def test_lookalike_hosts_and_junk_are_not_local(self):
        self.assertFalse(call("isLocalOnly", "https://grafana.example.com"))
        self.assertFalse(call("isLocalOnly", "https://grafana.holy-grail.ch.example.com"))
        self.assertFalse(call("isLocalOnly", "blank://blank"))
        self.assertFalse(call("isLocalOnly", "not a url"))


class Network(unittest.TestCase):
    def test_only_the_traefik_refusal_means_outside(self):
        self.assertEqual(call("networkFromStatus", 403), "outside")

    def test_a_served_page_or_redirect_means_home(self):
        for status in (200, 204, 302):
            self.assertEqual(call("networkFromStatus", status), "home", status)

    def test_anything_else_is_unknown_and_greys_nothing(self):
        for status in (0, 401, 429, 500, 502, 503):
            self.assertEqual(call("networkFromStatus", status), "unknown", status)


class Template(unittest.TestCase):
    def test_covers_grid_and_list_layouts(self):
        text = JS.read_text()
        self.assertIn("""[part="card"]""", text)
        self.assertIn("""[part="row"]""", text)

    def test_extends_the_stock_page_instead_of_copying_it(self):
        text = TEMPLATE.read_text()
        self.assertIn('{% extends "if/user.html" %}', text)
        self.assertIn("{{ block.super }}", text)
        self.assertIn('{% include "holy-grail/vpn-tiles.js" %}', text)

    def test_script_has_no_template_syntax(self):
        text = JS.read_text()
        for token in ("{{", "{%", "{#"):
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
