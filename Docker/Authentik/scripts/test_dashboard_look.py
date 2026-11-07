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


if __name__ == "__main__":
    unittest.main(verbosity=1)
