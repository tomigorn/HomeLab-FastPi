#!/usr/bin/env python3
"""Tests for due_dates.py. Run: python3 tests/test_due_dates.py"""
import datetime as dt
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("due_dates", HERE.parent / "due_dates.py")
dd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dd)

FIX = HERE / "fixtures"
D = dt.date
NOW = dt.datetime(2026, 11, 25, 10, 0, tzinfo=dt.timezone.utc)

SOURCE = """
[[due]]
id = "tm"
title = "Treasure Maps"
kind = "subscription"
category = "indexer"
date = 2031-11-17
show = ["seerr"]

[[due]]
id = "geek"
title = "NZBgeek"
kind = "subscription"
category = "indexer"
lifetime = true
show = ["seerr"]

[[due]]
id = "dom"
title = "holy-grail.ch"
kind = "domain"
source = "rdap"
registrar = "GoDaddy"
renew = "yearly at godaddy.com"
dns = "Cloudflare"

[[due]]
id = "noip"
title = "x.ddns.net"
kind = "ddns"
confirmed = 2026-11-10

[[due]]
id = "bak"
title = "Backup decision"
kind = "reminder"
date = 2026-12-22
lead = [7, 0]

[[due]]
id = "film"
title = "Film leaves the bin"
kind = "info"
date = 2026-11-29
"""


def build(source=SOURCE, textfiles=FIX):
    return dd.merge(dd.load_source(source), dd.fetch_textfiles(textfiles), NOW)


def by_id(data):
    return {i["id"]: i for i in data["items"]}


class Source(unittest.TestCase):
    def test_the_real_source_file_is_valid(self):
        items = dd.load_source((HERE.parent / "due-dates.toml").read_text())
        ids = [i["id"] for i in items]
        self.assertEqual(len(ids), len(set(ids)))
        for want in ("treasure-maps", "eweka", "protonvpn-plus", "nzbgeek", "nzbplanet", "mam-vip", "holy-grail-ch",
                     "noip-lang-tool", "noip-wg-aemtli", "dockerhub-wg-chores", "news-cve-backup"):
            self.assertIn(want, ids)

    def test_rejects_bad_entries(self):
        bad = [
            "x = [",
            '[[due]]\ntitle = "no id"\nkind = "subscription"\ndate = 2027-01-01\n',
            '[[due]]\nid = "a"\ntitle = "A"\nkind = "spaceship"\ndate = 2027-01-01\n',
            '[[due]]\nid = "a"\ntitle = "A"\nkind = "subscription"\n',
            '[[due]]\nid = "a"\ntitle = "A"\nkind = "subscription"\ndate = "2027-01-01"\n',
            '[[due]]\nid = "a"\ntitle = "A"\nkind = "subscription"\ndate = 2027-01-01\n[[due]]\nid = "a"\ntitle = "B"\nkind = "subscription"\ndate = 2027-01-01\n',
            '[[due]]\nid = "a"\ntitle = "A"\nkind = "subscription"\ndate = 2027-01-01\nlead = [7, "x"]\n',
            '[[due]]\nid = "a"\ntitle = "A"\nkind = "subscription"\ndate = 2027-01-01\nshow = ["tv"]\n',
            '[[due]]\nid = "a"\ntitle = "A"\nkind = "subscription"\ndate = 2027-01-01\nsource = "magic"\n',
        ]
        for text in bad:
            with self.assertRaises(ValueError, msg=text):
                dd.load_source(text)

    def test_domain_with_rdap_source_may_go_without_a_date(self):
        self.assertEqual(dd.load_source('[[due]]\nid = "d"\ntitle = "d.ch"\nkind = "domain"\nsource = "rdap"\n')[0]["id"], "d")


class Fetched(unittest.TestCase):
    def test_reads_the_recorded_textfiles(self):
        f = dd.fetch_textfiles(FIX)
        self.assertEqual(f["tls"], {"a.example.ch": "2027-01-15"})
        self.assertEqual(f["rdap"], {"holy-grail.ch": {"date": "2027-02-17", "source": "anniversary"}, "other.com": {"date": "2027-12-28", "source": "rdap"}})
        self.assertEqual(f["authentik"], {"avatar-picker-api": "2027-10-31"})

    def test_missing_textfiles_give_empty_sections(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(dd.fetch_textfiles(Path(d)), {"tls": {}, "rdap": {}, "authentik": {}})


class Merge(unittest.TestCase):
    def test_manual_entries_keep_their_date_and_defaults(self):
        i = by_id(build())
        self.assertEqual(i["tm"], {"id": "tm", "title": "Treasure Maps", "kind": "subscription", "category": "indexer", "date": "2031-11-17",
                                   "lifetime": False, "source": "manual", "lead": [30, 7, 0], "alert": "telegram", "show": ["seerr"]})
        self.assertTrue(i["geek"]["lifetime"])
        self.assertIsNone(i["geek"]["date"])

    def test_domain_without_date_takes_the_rdap_date(self):
        dom = by_id(build())["dom"]
        self.assertEqual((dom["date"], dom["source"]), ("2027-02-17", "anniversary"))
        self.assertEqual(dom["category"], "domain, GoDaddy (DNS Cloudflare)")
        self.assertEqual((dom["registrar"], dom["renew"], dom["dns"]), ("GoDaddy", "yearly at godaddy.com", "Cloudflare"))

    def test_a_date_set_by_hand_wins_over_rdap(self):
        src = SOURCE.replace('source = "rdap"\n', 'source = "rdap"\ndate = 2028-02-17\n')
        dom = by_id(build(src))["dom"]
        self.assertEqual((dom["date"], dom["source"]), ("2028-02-17", "manual"))

    def test_domain_without_any_date_stays_in_the_list_without_alert(self):
        with tempfile.TemporaryDirectory() as d:
            dom = by_id(build(textfiles=Path(d)))["dom"]
        self.assertIsNone(dom["date"])

    def test_ddns_is_confirmed_plus_30_days_with_short_leads(self):
        n = by_id(build())["noip"]
        self.assertEqual((n["date"], n["confirmed"], n["lead"], n["category"]), ("2026-12-10", "2026-11-10", [5, 3, 1, 0], "No-IP hostname"))

    def test_reminder_lead_and_info_without_alert(self):
        i = by_id(build())
        self.assertEqual(i["bak"]["lead"], [7, 0])
        self.assertEqual(i["film"]["alert"], "none")

    def test_fetched_certificates_and_tokens_are_listed_but_alerted_by_prometheus(self):
        i = by_id(build())
        self.assertEqual(i["tls:a.example.ch"], {"id": "tls:a.example.ch", "title": "TLS certificate a.example.ch", "kind": "certificate", "category": "Let's Encrypt via Traefik",
                                                 "date": "2027-01-15", "lifetime": False, "source": "tls", "lead": [21, 7], "alert": "prometheus", "show": []})
        self.assertEqual(i["authentik:avatar-picker-api"]["date"], "2027-10-31")
        self.assertEqual(i["authentik:avatar-picker-api"]["alert"], "prometheus")
        self.assertNotIn("rdap:other.com", i)

    def test_items_sorted_by_date_lifetime_last(self):
        ids = [x["id"] for x in build()["items"]]
        self.assertEqual(ids[0], "film")
        self.assertEqual(ids[-1], "geek")

    def test_header(self):
        data = build()
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["generated"], "2026-11-25T10:00:00Z")


class Run(unittest.TestCase):
    def test_run_writes_the_merged_list_and_the_fetched_state(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "due-dates.toml"
            src.write_text(SOURCE)
            out = Path(d) / "out"
            self.assertEqual(dd.run(src, FIX, out, NOW), 0)
            data = json.loads((out / "due-dates.json").read_text())
            self.assertIn("noip", [i["id"] for i in data["items"]])
            fetched = json.loads((out / "fetched.json").read_text())
            self.assertEqual(fetched["tls"], {"a.example.ch": "2027-01-15"})
            self.assertEqual(oct((out / "due-dates.json").stat().st_mode & 0o777), "0o644")

    def test_broken_source_keeps_the_old_list(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "due-dates.toml"
            src.write_text(SOURCE)
            out = Path(d) / "out"
            dd.run(src, FIX, out, NOW)
            before = (out / "due-dates.json").read_text()
            src.write_text("broken = [")
            self.assertEqual(dd.run(src, FIX, out, NOW), 1)
            self.assertEqual((out / "due-dates.json").read_text(), before)


class Markdown(unittest.TestCase):
    def test_page_lists_dated_items_soonest_first_and_folds_certificates(self):
        md = dd.markdown(build(), D(2026, 11, 25))
        lines = md.splitlines()
        self.assertTrue(lines[0].startswith("# "))
        rows = [l for l in lines if l.startswith("| 20") or l.startswith("| lifetime")]
        self.assertTrue(rows[0].startswith("| 2026-11-29 | 4 days | Film leaves the bin"))
        self.assertIn("| 2026-12-10 | 15 days | x.ddns.net · No-IP hostname |", md)
        self.assertIn("TLS certificates (1, Prometheus alerts)", md)
        self.assertNotIn("tls:a.example.ch", md)
        self.assertIn("| lifetime | | NZBgeek · indexer |", md)
        self.assertIn("Due-Dates/due-dates.toml", md)

    def test_pipes_in_text_are_escaped(self):
        src = '[[due]]\nid = "p"\ntitle = "A|B"\nkind = "info"\ndate = 2027-01-01\n'
        with tempfile.TemporaryDirectory() as d:
            md = dd.markdown(dd.merge(dd.load_source(src), dd.fetch_textfiles(Path(d)), NOW), D(2026, 11, 25))
        self.assertIn("A\\|B", md)


if __name__ == "__main__":
    sys.exit(unittest.main())
