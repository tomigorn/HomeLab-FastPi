#!/usr/bin/env python3
"""Reads under the library must not restart the quiet wait. Run inside the image: python3 /app/test_watcher.py"""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import watcher  # noqa: E402


class Handler(unittest.TestCase):
    def setUp(self):
        watcher._dirty = False

    def fire(self, kind):
        watcher.Handler().on_any_event(SimpleNamespace(event_type=kind, src_path="/lib/x.mp3", is_directory=False))
        return watcher._dirty

    def test_reads_are_ignored(self):
        self.assertFalse(self.fire("opened"))
        self.assertFalse(self.fire("closed_no_write"))

    def test_changes_mark_dirty(self):
        for kind in ("created", "modified", "moved", "deleted", "closed"):
            watcher._dirty = False
            self.assertTrue(self.fire(kind), kind)


if __name__ == "__main__":
    unittest.main()
