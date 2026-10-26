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

    def test_never_spends_wedges(self):
        self.assertIs(self.values["useFreeleechWedge"], False)

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
        values = {"useFreeleechWedge": False, "searchType": 1, "searchLanguages": [1, 37]}
        values.update(over)
        return {"name": "MyAnonamouse", "implementation": "MyAnonamouse", "supportsRss": False,
                "fields": [{"name": k, "value": v} for k, v in values.items()]}

    def test_safe_indexer_passes(self):
        self.assertEqual(ps.problems([self.indexer()]), [])

    def test_wedge_on_is_reported(self):
        self.assertTrue(any("useFreeleechWedge" in p for p in ps.problems([self.indexer(useFreeleechWedge=True)])))

    def test_wrong_search_type_is_reported(self):
        self.assertTrue(ps.problems([self.indexer(searchType=0)]))

    def test_missing_mam_is_reported(self):
        self.assertTrue(ps.problems([]))


if __name__ == "__main__":
    unittest.main()
