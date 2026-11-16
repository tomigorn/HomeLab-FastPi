#!/usr/bin/env python3
"""Tests for library_exporter.py.   python3 test_library_exporter.py"""
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import library_exporter as ex  # noqa: E402


def touch(root, rel, size):
    p = pathlib.Path(root, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)


class Scan(unittest.TestCase):
    def test_bytes_and_items_fold_disc_folders(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "EN/Jane Doe/Book One/part1.m4b", 100)
            touch(d, "EN/Jane Doe/Book One/cover.jpg", 5)
            touch(d, "EN/John Roe/Saga/Book Two/CD 1/a.mp3", 10)
            touch(d, "EN/John Roe/Saga/Book Two/Disc2/b.mp3", 20)
            touch(d, "DE/Max Muster/Buch/x.m4b", 7)
            touch(d, "EN/Jane Doe/Book One/.hidden", 1000)
            self.assertEqual(ex.scan(d), (142, 3))

    def test_files_in_the_root_are_no_item(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "stray.txt", 3)
            self.assertEqual(ex.scan(d), (3, 0))


class Lines(unittest.TestCase):
    def test_present_and_missing_categories(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "books/A/B/x.m4b", 50)
            os.mkdir(os.path.join(d, "empty"))
            cfg = {"audiobooks": {"paths": [os.path.join(d, "books")]}, "podcasts": {"paths": [os.path.join(d, "empty")]},
                   "ebooks": {"paths": []}, "music": {"paths": [os.path.join(d, "nope")]}}
            t = ex.lines(cfg, now=1000)
        self.assertIn('fastpi_library_present{category="audiobooks"} 1', t)
        self.assertIn('fastpi_library_bytes{category="audiobooks"} 50', t)
        self.assertIn('fastpi_library_items{category="audiobooks"} 1', t)
        self.assertIn('fastpi_library_present{category="podcasts"} 1', t)
        self.assertIn('fastpi_library_bytes{category="podcasts"} 0', t)
        self.assertIn('fastpi_library_present{category="ebooks"} 0', t)
        self.assertIn('fastpi_library_present{category="music"} 0', t)
        self.assertNotIn('fastpi_library_bytes{category="music"}', t)
        self.assertIn("fastpi_library_updated_timestamp_seconds 1000", t)

    def test_shipped_config_lists_the_owner_categories(self):
        cfg = ex.load(pathlib.Path(__file__).with_name("libraries.toml"))
        self.assertEqual(sorted(cfg), ["audiobooks", "ebooks", "music", "podcasts"])


class Write(unittest.TestCase):
    def test_atomic_and_world_readable(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d, "library_fastpi.prom")
            ex.write(out, "a 1\n")
            self.assertEqual((out.read_text(), oct(out.stat().st_mode & 0o777)), ("a 1\n", "0o644"))


if __name__ == "__main__":
    unittest.main()
