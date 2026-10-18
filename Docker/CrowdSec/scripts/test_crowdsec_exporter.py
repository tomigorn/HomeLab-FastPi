#!/usr/bin/env python3
"""Tests for the pure parts of crowdsec_exporter.py.   python3 test_crowdsec_exporter.py"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crowdsec_exporter as ex  # noqa: E402

NOW = ex.parse_ts("2026-10-19T00:00:00Z")


def alert(i, t="2026-10-18T22:00:00Z", kind="crowdsec", scenario="crowdsecurity/http-probing",
          ip="1.2.3.4", cn="RU", simulated=False):
    return {"id": i, "created_at": t, "kind": kind, "scenario": scenario, "simulated": simulated,
            "source": {"ip": ip, "cn": cn, "as_name": "AS Test"}}


class Ingest(unittest.TestCase):
    def test_counts_only_real_attacks(self):
        s = {}
        n = ex.ingest_alerts(s, [alert(1), alert(2, kind="cscli", scenario="test: x"),
                                 alert(3, kind="capi", scenario="update : +15000/-0 IPs"),
                                 alert(4, kind=None), alert(5, simulated=True)], NOW)
        self.assertEqual(n, 2)                     # id 1 + legacy kind=None id 4
        self.assertEqual(s["by_country"], {"RU": 2})
        self.assertEqual(s["last_id"], 5)

    def test_counters_only_increase_and_dedupe(self):
        s = {}
        ex.ingest_alerts(s, [alert(1), alert(2)], NOW)
        ex.ingest_alerts(s, [alert(2), alert(3, cn="CN")], NOW)   # overlap window
        self.assertEqual(s["by_country"], {"RU": 2, "CN": 1})
        # CrowdSec flushed old alerts from its DB: counters must not drop.
        ex.ingest_alerts(s, [], NOW)
        self.assertEqual(sum(s["by_country"].values()), 3)

    def test_db_restore_reuses_ids(self):
        s = {}
        a, b = alert(100), alert(100, cn="DE")       # same id, different alert
        a["uuid"], b["uuid"] = "u-1", "u-2"
        ex.ingest_alerts(s, [a], NOW)
        ex.ingest_alerts(s, [b], NOW)                   # id reused after a DB restore
        self.assertEqual(s["by_country"], {"RU": 1, "DE": 1})

    def test_legacy_state_not_recounted(self):
        s = {"last_id": 5, "by_country": {"RU": 5}, "recent": []}
        ex.ingest_alerts(s, [alert(4), alert(5), alert(6)], NOW)
        self.assertEqual(s["by_country"], {"RU": 6})
        ex.ingest_alerts(s, [alert(6)], NOW)
        self.assertEqual(s["by_country"], {"RU": 6})

    def test_recent_pruned_to_7d(self):
        s = {}
        ex.ingest_alerts(s, [alert(1, t="2026-10-01T00:00:00Z"), alert(2)], NOW)
        self.assertEqual([r["id"] for r in s["recent"]], [2])
        self.assertEqual(s["by_country"]["RU"], 2)              # lifetime keeps both

    def test_missing_country(self):
        s = {}
        ex.ingest_alerts(s, [alert(1, cn=None)], NOW)
        self.assertEqual(s["by_country"], {"unknown": 1})


class Dropped(unittest.TestCase):
    def test_monotonic_through_lapi_flush(self):
        s = {}
        ex.ingest_dropped(s, {"traefik-bouncer": 100})   # backfill
        ex.ingest_dropped(s, {"traefik-bouncer": 130})
        ex.ingest_dropped(s, {"traefik-bouncer": 20})    # LAPI flushed old pushes
        ex.ingest_dropped(s, {"traefik-bouncer": 25})
        self.assertEqual(s["dropped_total"]["traefik-bouncer"], 135)


class Render(unittest.TestCase):
    LINE = re.compile(r'^(# (HELP|TYPE) .*|[a-z_][a-z0-9_]*(\{([a-z_]+="([^"\\]|\\.)*",?)*\})? -?[0-9.e+]+)$')

    def test_exposition_is_valid(self):
        s = {}
        ex.ingest_alerts(s, [alert(1), alert(2, ip='5.6.7.8', cn="US"),
                             alert(3, scenario='weird "quoted"\\name/x')], NOW)
        ex.ingest_dropped(s, {"traefik-bouncer": 7})
        txt = ex.render(s, NOW, {"RU": "Russian Federation"},
                        {"bouncer_last_pull": {"traefik-bouncer": NOW}, "capi_last_pull": NOW,
                         "hub_index_mtime": NOW, "hub_items_not_ok": 0,
                         "data_files": {"GeoLite2-City.mmdb": NOW}})
        for line in txt.strip().splitlines():
            self.assertRegex(line, self.LINE)
        self.assertIn(f'crowdsec_data_file_timestamp_seconds{{file="GeoLite2-City.mmdb"}} {NOW:.0f}', txt)
        self.assertIn('crowdsec_attacks_recent{window="24h"} 3', txt)
        self.assertIn('country_name="Russian Federation"', txt)
        self.assertIn('crowdsec_bouncer_dropped_requests_total{bouncer="traefik-bouncer"} 7', txt)

    def test_zero_series_precreated(self):
        s = {}
        ex.ingest_alerts(s, [alert(1)], NOW)
        txt = ex.render(s, NOW, {"RU": "Russia", "DE": "Germany"}, {"scenarios": ["crowdsecurity/ssh-bf"]})
        self.assertIn('crowdsec_attacks_by_country_total{country="DE",country_name="Germany"} 0', txt)
        self.assertIn('crowdsec_attacks_by_country_total{country="RU",country_name="Russia"} 1', txt)
        self.assertIn('crowdsec_attacks_by_scenario_total{scenario="crowdsecurity/ssh-bf"} 0', txt)

    def test_top_n_bounded(self):
        s = {}
        ex.ingest_alerts(s, [alert(i, ip=f"10.0.0.{i}") for i in range(1, 60)], NOW)
        txt = ex.render(s, NOW, {}, {})
        self.assertEqual(txt.count("crowdsec_top_attacker_attacks_24h{"), ex.TOP_N)


if __name__ == "__main__":
    unittest.main(verbosity=1)
