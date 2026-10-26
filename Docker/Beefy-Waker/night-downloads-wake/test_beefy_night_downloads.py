#!/usr/bin/env python3
"""beefy-night-downloads: the poll keeps beefy's last pending count without waking it, the 22:05 wake fires only when downloads wait.
Usage: python3 test_beefy_night_downloads.py"""
import importlib.machinery
import importlib.util
import json
import pathlib
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
loader = importlib.machinery.SourceFileLoader("bnd", str(HERE / "beefy-night-downloads"))
spec = importlib.util.spec_from_loader("bnd", loader)
bnd = importlib.util.module_from_spec(spec)
loader.exec_module(bnd)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = pathlib.Path(self.tmp.name) / "state.json"
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def env(self, up, remote='{"pending": 2, "low_tariff": false, "updated": "2026-10-26T14:00:00"}', wake_rc=0):
        def is_up():
            self.calls.append("status")
            return up

        def fetch():
            self.calls.append("ssh")
            if isinstance(remote, Exception):
                raise remote
            return remote

        def wake():
            self.calls.append("wake")
            return wake_rc
        return dict(is_up=is_up, fetch=fetch, wake=wake, cache=self.cache)


class Poll(Base):
    def test_awake_beefy_state_is_cached(self):
        self.assertEqual(bnd.poll(**self.env(True)), 0)
        self.assertEqual(json.loads(self.cache.read_text())["pending"], 2)

    def test_asleep_beefy_is_not_contacted_and_cache_kept(self):
        self.cache.write_text('{"pending": 5}')
        self.assertEqual(bnd.poll(**self.env(False)), 0)
        self.assertEqual(self.calls, ["status"])
        self.assertEqual(json.loads(self.cache.read_text())["pending"], 5)

    def test_unreadable_answer_keeps_the_cache(self):
        self.cache.write_text('{"pending": 5}')
        for bad in ("not json", '{"pending": "x"}', '{"other": 1}', bnd.FetchError("ssh failed")):
            self.assertEqual(bnd.poll(**self.env(True, remote=bad)), 1, bad)
            self.assertEqual(json.loads(self.cache.read_text())["pending"], 5)


class Wake(Base):
    def test_downloads_waiting_and_beefy_asleep_wakes(self):
        self.cache.write_text('{"pending": 2}')
        self.assertEqual(bnd.wake_if_waiting(**self.env(False)), 0)
        self.assertEqual(self.calls, ["status", "wake"])

    def test_nothing_waiting_no_wake(self):
        self.cache.write_text('{"pending": 0}')
        self.assertEqual(bnd.wake_if_waiting(**self.env(False)), 0)
        self.assertNotIn("wake", self.calls)

    def test_no_cache_yet_no_wake(self):
        self.assertEqual(bnd.wake_if_waiting(**self.env(False)), 0)
        self.assertNotIn("wake", self.calls)

    def test_beefy_awake_is_left_to_its_own_timer(self):
        self.cache.write_text('{"pending": 3}')
        self.assertEqual(bnd.wake_if_waiting(**self.env(True)), 0)
        self.assertNotIn("wake", self.calls)

    def test_dry_run_never_wakes(self):
        self.cache.write_text('{"pending": 3}')
        self.assertEqual(bnd.wake_if_waiting(dry_run=True, **self.env(False)), 0)
        self.assertNotIn("wake", self.calls)

    def test_failed_wake_fails_the_unit(self):
        self.cache.write_text('{"pending": 1}')
        self.assertEqual(bnd.wake_if_waiting(**self.env(False, wake_rc=1)), 1)


if __name__ == "__main__":
    unittest.main()
