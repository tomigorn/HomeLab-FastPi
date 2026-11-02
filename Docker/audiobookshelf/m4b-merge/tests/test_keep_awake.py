#!/usr/bin/env python3
"""KeepAwake takes and releases beefy's inhibit file only when nobody else holds it.

Run: ./tests/test_keep_awake.py
"""
import importlib.util
import os
import unittest
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("orch", os.path.join(HERE, "orchestrate.py"))
orch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orch)


def fake_remote(held):
    calls = []

    def ssh(script, timeout=None):
        action = script.split()[-1]
        calls.append(action)
        out = ("held" if held else "released") + "\n" if action == "status" else ""
        return SimpleNamespace(returncode=0, stdout=out)
    return ssh, calls


class KeepAwake(unittest.TestCase):
    def test_free_hold_is_taken_and_released(self):
        orch.ssh, calls = fake_remote(held=False)
        with orch.KeepAwake():
            pass
        self.assertEqual([c for c in calls if c != "status"], ["on", "off"])

    def test_someone_elses_hold_is_left_alone(self):
        orch.ssh, calls = fake_remote(held=True)
        with orch.KeepAwake():
            pass
        self.assertNotIn("off", calls)
        self.assertNotIn("on", calls)


if __name__ == "__main__":
    unittest.main()
