#!/usr/bin/env python3
"""Tests for the custom CSS in dashboard-look.py. python3 test_dashboard_look.py"""
import ast
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

    def test_nextcloud_is_a_utility(self):
        self.assertEqual(re.search(r'"nextcloud":\s*\("(\w+)"', SOURCE).group(1), "Utilities")


if __name__ == "__main__":
    unittest.main(verbosity=1)
