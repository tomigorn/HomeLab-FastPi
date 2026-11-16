#!/usr/bin/env python3
"""Board "CVE feed resources" (provisioning/dashboards/cve-feed-resources.json).   python3 scripts/test_cve_feed_board.py"""
import json
import pathlib
import unittest

BOARD = json.loads((pathlib.Path(__file__).resolve().parent.parent / "provisioning" / "dashboards" / "cve-feed-resources.json").read_text())
CONTAINERS = "vl-web|vl-feeder|vl-kvrocks|vl-cache|vl-db|miniflux|miniflux-db"
PANELS = [p for p in BOARD["panels"] if p["type"] != "row"]


def queries(p):
    return [t.get("query") or t.get("expr") or "" for t in p.get("targets", [])]


class Board(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(BOARD["uid"], "cve-feed-resources")
        self.assertEqual(BOARD["title"], "CVE feed resources")

    def test_every_metric_is_there(self):
        titles = " ".join(p["title"].lower() for p in PANELS)
        for word in ("ram working set", "ram peak", "cpu", "swap", "network", "block i/o", "disk"):
            self.assertIn(word, titles)

    def test_container_panels_are_filtered_to_the_stack(self):
        for p in PANELS:
            if "host" in p["title"].lower():
                continue
            for q in queries(p):
                with self.subTest(panel=p["title"]):
                    self.assertTrue(CONTAINERS in q or f'"{CONTAINERS}"' in q, q)

    def test_working_set_leaves_out_reclaimable_cache(self):
        p = next(p for p in PANELS if "working set" in p["title"].lower())
        self.assertIn("inactive_file", queries(p)[0])

    def test_phone_friendly_widths(self):
        for p in PANELS:
            self.assertIn(p["gridPos"]["w"], (12, 24), p["title"])


if __name__ == "__main__":
    unittest.main()
