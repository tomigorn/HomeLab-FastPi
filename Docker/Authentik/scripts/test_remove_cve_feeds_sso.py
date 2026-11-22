"""Tests for remove-cve-feeds-sso.py. Run: python3 -m unittest discover -s Docker/Authentik/scripts"""
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("remove_cve_feeds_sso", HERE / "remove-cve-feeds-sso.py")
rcs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rcs)


class TargetsTest(unittest.TestCase):
    def test_only_the_two_provisioned_apps(self):
        self.assertEqual(rcs.TARGETS, (("cve", "cve-proxy"), ("news", "news-proxy")))

    def test_only_the_embedded_outpost(self):
        self.assertEqual(rcs.OUTPOST, "authentik Embedded Outpost")


class ApplyTest(unittest.TestCase):
    def test_dry_run_is_the_default(self):
        self.assertFalse(rcs.wants_apply({}))
        self.assertFalse(rcs.wants_apply({"APPLY": "0"}))

    def test_apply_only_on_one(self):
        self.assertTrue(rcs.wants_apply({"APPLY": "1"}))


class StepsTest(unittest.TestCase):
    def test_everything_present_in_deletion_order(self):
        got = rcs.steps({"cve": ["a", "b"], "news": ["a"]}, {"cve-proxy", "news-proxy"}, {"cve-proxy", "news-proxy"})
        self.assertEqual(got, [
            "binding cve <- a", "binding cve <- b", "application cve", "outpost assignment cve-proxy", "provider cve-proxy",
            "binding news <- a", "application news", "outpost assignment news-proxy", "provider news-proxy"])

    def test_nothing_left_is_empty(self):
        self.assertEqual(rcs.steps({}, set(), set()), [])

    def test_partial_state_lists_only_what_remains(self):
        self.assertEqual(rcs.steps({}, {"news-proxy"}, set()), ["provider news-proxy"])

    def test_foreign_objects_are_ignored(self):
        self.assertEqual(rcs.steps({"other": ["g"]}, {"other-proxy"}, {"other-proxy"}), [])


if __name__ == "__main__":
    unittest.main()
