#!/usr/bin/env python3
"""Tests for the custom CSS in dashboard-look.py. python3 test_dashboard_look.py"""
import ast
import os
import re
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parent / "dashboard-look.py").read_text()
CSS = next(ast.literal_eval(n.value) for n in ast.parse(SOURCE).body
           if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "CUSTOM_CSS")


class PhoneScrolling(unittest.TestCase):
    def test_app_area_uses_the_visible_height(self):
        rule = re.search(r"\.pf-c-drawer__main\s*\{([^}]*)\}", CSS)
        self.assertIsNotNone(rule)
        self.assertIn("min-height: calc(100dvh - 76px) !important", rule.group(1))
        self.assertIn("max-height: calc(100dvh - 76px) !important", rule.group(1))


class Sections(unittest.TestCase):
    def test_activity_has_section_description_and_icon(self):
        m = re.search(r'"activity":\s*\("(\w+)",\s*"([^"]+)",\s*"(fa://[\w-]+)"\)', SOURCE)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "Media")

    def test_tech_radar_has_section_description_and_icon(self):
        m = re.search(r'"tech-radar":\s*\("(\w+)",\s*"([^"]+)",\s*"(fa://[\w-]+)"\)', SOURCE)
        self.assertIsNotNone(m)
        self.assertEqual(m.groups(), ("Utilities", "My tech stack", "fa://fa-layer-group"))

    def test_wiki_admin_has_section_description_and_icon(self):
        m = re.search(r'"wiki-admin":\s*\("(\w+)",\s*"([^"]+)",\s*"(fa://[\w-]+)"\)', SOURCE)
        self.assertIsNotNone(m)
        self.assertEqual(m.groups(), ("Account", "Admin guide", "fa://fa-user-shield"))

    def test_cve_feeds_are_homelab_tiles_with_icons(self):
        for slug, desc, icon in (("cve", "CVE lookup & watchlist", "fa://fa-bug"),
                                 ("news", "Security news & releases", "fa://fa-rss")):
            m = re.search(rf'"{slug}":\s*\("(\w+)",\s*"([^"]+)",\s*"(fa://[\w-]+)"\)', SOURCE)
            self.assertIsNotNone(m, slug)
            self.assertEqual(m.groups(), ("Homelab", desc, icon))

    def test_nextcloud_is_a_utility(self):
        self.assertEqual(re.search(r'"nextcloud":\s*\("(\w+)"', SOURCE).group(1), "Utilities")

    def test_wg_chores_is_a_utility_with_its_app_icon(self):
        m = re.search(r'"wg-chores":\s*\("(\w+)",\s*"([^"]+)",\s*None\)', SOURCE)
        self.assertIsNotNone(m)
        self.assertEqual(m.groups(), ("Utilities", "Shared household chores"))
        icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "icons", "wg-chores.svg")
        self.assertTrue(os.path.exists(icon))
        self.assertIn("#2a55c5", open(icon).read())

    def test_report_tile_has_own_icon_and_a_short_description(self):
        m = re.search(r'"report":\s*\("(\w+)",\s*"([^"]+)"\s*\+\s*BEEFY,\s*None\)', SOURCE)
        self.assertIsNotNone(m)
        self.assertEqual(m.groups(), ("Media", "Report a broken film"))
        icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "icons", "report.svg")
        svg = open(icon).read()
        self.assertIn('viewBox="0 0 192 192"', svg)
        self.assertIn('rx="40"', svg)


def rule(selector_regex):
    m = re.search(selector_regex + r"\s*\{([^}]*)\}", CSS)
    return m.group(1) if m else ""


class StickyHeader(unittest.TestCase):
    HEADER = r'\n\.pf-c-page__main:has\(> main \[part="app-list"\]\) > \.pf-c-page__header'
    BANNER = r"\n#hg-vpn-banner"

    def test_header_sticks_to_the_top_of_the_scrolling_list(self):
        body = rule(self.HEADER)
        self.assertIn("position: sticky", body)
        self.assertIn("top: 0", body)
        self.assertIn("height: calc(var(--hg-head-height) + var(--hg-head-gap))", body)
        self.assertRegex(body, r"background: #fff")

    def test_dark_header_is_the_fixed_navy_page_background(self):
        body = rule(r':host\(\[theme="dark"\]\) \.pf-c-page__main:has\(> main \[part="app-list"\]\) > \.pf-c-page__header')
        self.assertIn("linear-gradient(180deg, #0b1628, #0a1220 60%, #080d18) fixed", body)

    def test_stock_overflow_hidden_no_longer_traps_sticky(self):
        self.assertIn("overflow: clip", rule(r'\n\.pf-c-page__main:has\(> main \[part="app-list"\]\)'))

    def test_banner_sticks_right_under_the_header(self):
        body = rule(self.BANNER)
        self.assertIn("position: sticky", body)
        self.assertIn("top: calc(var(--hg-head-height) + var(--hg-head-gap))", body)

    def test_header_heights_per_layout(self):
        heights = re.findall(r"--hg-head-height: (\d+)px", CSS)
        self.assertEqual(heights, ["76", "88", "83"])

    def test_header_and_banner_are_above_the_vpn_veil_and_badge(self):
        js = (Path(__file__).resolve().parent.parent / "custom-templates" / "holy-grail" / "vpn-tiles.js").read_text()
        tiles = max(int(z) for z in re.findall(r"z-index:(\d+)", js))
        header = int(re.search(r"z-index: (\d+)", rule(self.HEADER)).group(1))
        banner = int(re.search(r"z-index: (\d+)", rule(self.BANNER)).group(1))
        self.assertGreater(header, tiles)
        self.assertGreater(banner, header)


if __name__ == "__main__":
    unittest.main(verbosity=1)
