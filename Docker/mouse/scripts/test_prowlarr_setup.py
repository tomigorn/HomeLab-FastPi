"""Tests for prowlarr-setup.py. Run: python3 -m unittest discover -s Docker/mouse/scripts"""
import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("prowlarr_setup", Path(__file__).parent / "prowlarr-setup.py")
ps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ps)


def schema(fields):
    return {"implementation": "MyAnonamouse", "fields": [{"name": k, "value": v} for k, v in fields.items()]}


class MamFieldsTest(unittest.TestCase):
    def setUp(self):
        self.out = ps.fill(schema({"baseUrl": None, "mamId": "", "searchType": 0, "searchLanguages": [],
                                   "useFreeleechWedge": True, "searchInDescription": False}), ps.MAM_FIELDS, mam_id="x")
        self.values = {f["name"]: f["value"] for f in self.out["fields"]}

    def test_uses_a_wedge_on_torrents_that_are_not_free_already(self):
        self.assertIs(self.values["useFreeleechWedge"], True)

    def test_active_search_english_and_german(self):
        self.assertEqual(self.values["searchType"], 1)
        self.assertEqual(sorted(self.values["searchLanguages"]), [1, 37])

    def test_session_and_url(self):
        self.assertEqual(self.values["mamId"], "x")
        self.assertEqual(self.values["baseUrl"], "https://www.myanonamouse.net/")

    def test_no_rss(self):
        self.assertIs(self.out["supportsRss"], False)


class CheckTest(unittest.TestCase):
    def indexer(self, **over):
        values = {"useFreeleechWedge": True, "searchType": 1, "searchLanguages": [1, 37]}
        values.update(over)
        return {"name": "MyAnonamouse", "implementation": "MyAnonamouse", "supportsRss": False,
                "fields": [{"name": k, "value": v} for k, v in values.items()]}

    def test_safe_indexer_passes(self):
        self.assertEqual(ps.problems([self.indexer()]), [])

    def test_wedge_off_is_reported(self):
        self.assertTrue(any("useFreeleechWedge" in p for p in ps.problems([self.indexer(useFreeleechWedge=False)])))

    def test_wrong_search_type_is_reported(self):
        self.assertTrue(ps.problems([self.indexer(searchType=0)]))

    def test_missing_mam_is_reported(self):
        self.assertTrue(ps.problems([]))


if __name__ == "__main__":
    unittest.main()


class HostLockdownTest(unittest.TestCase):
    def test_prowlarr_listens_on_loopback_only_behind_the_gate(self):
        body = ps.host_lockdown({"id": 1, "bindAddress": "*", "authenticationMethod": "none", "port": 9696})
        self.assertEqual((body["bindAddress"], body["authenticationMethod"], body["authenticationRequired"]),
                         ("127.0.0.1", "external", "enabled"))
        self.assertEqual(body["port"], 9696)

    def test_lockdown_problems(self):
        self.assertEqual(ps.auth_problems({"bindAddress": "127.0.0.1", "authenticationMethod": "external"}), [])
        self.assertTrue(ps.auth_problems({"bindAddress": "*", "authenticationMethod": "external"}))


class ShareLimitTest(unittest.TestCase):
    PREFS = {"max_ratio_enabled": False, "max_seeding_time_enabled": False, "max_inactive_seeding_time_enabled": False}
    CATS = {"abr": {"ratio_limit": -2, "seeding_time_limit": -2, "inactive_seeding_time_limit": -2}}

    def test_seed_forever_passes(self):
        self.assertEqual(ps.share_problems(self.PREFS, self.CATS), [])

    def test_a_global_ratio_limit_is_reported(self):
        self.assertTrue(ps.share_problems(dict(self.PREFS, max_ratio_enabled=True), self.CATS))

    def test_a_category_seeding_limit_is_reported(self):
        self.assertTrue(ps.share_problems(self.PREFS, {"abr": {"ratio_limit": -2, "seeding_time_limit": 4320}}))
