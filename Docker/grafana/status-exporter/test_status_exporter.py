#!/usr/bin/env python3
"""Tests for status_exporter.py.   python3 test_status_exporter.py"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import status_exporter as ex  # noqa: E402

NOW = dt.datetime(2026, 10, 29, 1, 0, tzinfo=dt.timezone.utc).timestamp()


class RoutedHosts(unittest.TestCase):
    def test_only_routers_with_a_cert_resolver(self):
        docs = [
            {"http": {"routers": {
                "a": {"rule": "Host(`sso.holy-grail.ch`)", "tls": {"certResolver": "cloudflare"}},
                "b": {"rule": "Host(`x.holy-grail.ch`) && PathPrefix(`/api`)", "tls": {"certResolver": "cloudflare"}},
                "c": {"rule": "Host(`beefy-wol.fastpi.homelab`)", "tls": {}},
                "d": {"rule": "Host(`plain.holy-grail.ch`)"},
                "e": {"rule": "Host(`lang-tool.ddns.net`) || Host(`y.holy-grail.ch`, `z.holy-grail.ch`)", "tls": {"certResolver": "le"}},
            }}},
            None,
            {"http": {"middlewares": {}}},
        ]
        self.assertEqual(ex.routed_hosts(docs), ["lang-tool.ddns.net", "sso.holy-grail.ch", "x.holy-grail.ch", "y.holy-grail.ch", "z.holy-grail.ch"])


class Certs(unittest.TestCase):
    def test_lines(self):
        text = ex.cert_lines({
            "a.holy-grail.ch": {"ok": True, "not_after": 1800000000, "verified": True},
            "b.holy-grail.ch": {"ok": True, "not_after": 1790000000, "verified": False},
            "c.holy-grail.ch": {"ok": False}}, NOW)
        self.assertIn('tls_cert_probe_success{host="a.holy-grail.ch"} 1', text)
        self.assertIn('tls_cert_not_after_timestamp_seconds{host="a.holy-grail.ch"} 1800000000', text)
        self.assertIn('tls_cert_verified{host="b.holy-grail.ch"} 0', text)
        self.assertIn('tls_cert_probe_success{host="c.holy-grail.ch"} 0', text)
        self.assertNotIn('tls_cert_not_after_timestamp_seconds{host="c.holy-grail.ch"}', text)
        self.assertIn(f"tls_cert_exporter_last_run_timestamp_seconds {int(NOW)}", text)


class Domains(unittest.TestCase):
    CH = {"ldhName": "holy-grail.ch", "status": ["active"], "events": [{"eventAction": "registration", "eventDate": "2021-09-12"}]}
    NET = {"ldhName": "example.net", "status": ["client transfer prohibited"], "events": [
        {"eventAction": "registration", "eventDate": "2001-06-28T16:04:59Z"},
        {"eventAction": "expiration", "eventDate": "2027-06-28T16:04:59Z"}]}

    def test_rdap_expiration_wins(self):
        d = ex.domain_info(self.NET, {}, NOW)
        self.assertEqual((d["source"], d["status_ok"]), ("rdap", 1))
        self.assertEqual(d["expires"], dt.datetime(2027, 6, 28, 16, 4, 59, tzinfo=dt.timezone.utc).timestamp())

    def test_manual_date_beats_anniversary(self):
        d = ex.domain_info(self.CH, {"expires": dt.date(2028, 9, 12)}, NOW)
        self.assertEqual(d["source"], "manual")
        self.assertEqual(d["expires"], ex.local_midnight(dt.date(2028, 9, 12)))

    def test_no_expiry_uses_next_registration_anniversary(self):
        d = ex.domain_info(self.CH, {}, NOW)
        self.assertEqual(d["source"], "anniversary")
        self.assertEqual(d["expires"], ex.local_midnight(dt.date(2027, 9, 12)))

    def test_anniversary_later_this_year(self):
        d = ex.domain_info(self.CH, {}, dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc).timestamp())
        self.assertEqual(d["expires"], ex.local_midnight(dt.date(2026, 9, 12)))

    def test_bad_status(self):
        for st in (["inactive"], ["active", "server hold"], ["pending delete"], ["redemption period"], ["client hold"]):
            self.assertEqual(ex.domain_info({**self.CH, "status": st}, {}, NOW)["status_ok"], 0, st)

    def test_lines(self):
        text = ex.domain_lines({"holy-grail.ch": {"expires": 1820000000, "source": "anniversary", "status_ok": 1}, "broken.ch": None}, NOW)
        self.assertIn('domain_expiry_timestamp_seconds{domain="holy-grail.ch",source="anniversary"} 1820000000', text)
        self.assertIn('domain_rdap_status_ok{domain="holy-grail.ch"} 1', text)
        self.assertIn('domain_rdap_success{domain="holy-grail.ch"} 1', text)
        self.assertIn('domain_rdap_success{domain="broken.ch"} 0', text)

    def test_rdap_base(self):
        boot = {"services": [[["net", "com"], ["https://rdap.verisign.com/net/v1/"]]]}
        self.assertEqual(ex.rdap_url("example.net", boot), "https://rdap.verisign.com/net/v1/domain/example.net")
        self.assertEqual(ex.rdap_url("holy-grail.ch", boot), "https://rdap.nic.ch/domain/holy-grail.ch")


class Ddns(unittest.TestCase):
    def test_lines(self):
        text = ex.ddns_lines({"a.ddns.net": ["1.2.3.4"], "b.ddns.net": [], "c.ddns.net": ["5.6.7.8"]}, "1.2.3.4")
        self.assertIn('ddns_hostname_resolves{host="a.ddns.net"} 1', text)
        self.assertIn('ddns_hostname_matches_wan{host="a.ddns.net"} 1', text)
        self.assertIn('ddns_hostname_resolves{host="b.ddns.net"} 0', text)
        self.assertIn('ddns_hostname_matches_wan{host="c.ddns.net"} 0', text)

    def test_unknown_wan_skips_match(self):
        self.assertNotIn("matches_wan", ex.ddns_lines({"a.ddns.net": ["1.2.3.4"]}, None))

    def test_wan_from_trace(self):
        self.assertEqual(ex.wan_from_trace("fl=1\nip=84.1.2.3\nts=1\n"), "84.1.2.3")
        self.assertIsNone(ex.wan_from_trace("garbage"))


class Subscriptions(unittest.TestCase):
    TOML = 'x = 1\n[[subscriptions]]\nname = "Eweka"\nkind = "Usenet provider"\nexpires = 2026-11-18\n\n[[subscriptions]]\nname = "NZBgeek"\nkind = "indexer"\nlifetime = true\n'

    def test_lines(self):
        text = ex.subscription_lines(self.TOML, {"vip_expires": "2027-01-27"}, 1793000000)
        self.assertIn(f'subscription_expiry_timestamp_seconds{{name="Eweka",kind="Usenet provider"}} {int(ex.local_midnight(dt.date(2026, 11, 18)))}', text)
        self.assertIn('subscription_lifetime{name="NZBgeek",kind="indexer"} 1', text)
        self.assertIn(f'subscription_expiry_timestamp_seconds{{name="MAM VIP",kind="MyAnonamouse class"}} {int(ex.local_midnight(dt.date(2027, 1, 27)))}', text)
        self.assertIn("subscription_list_updated_timestamp_seconds 1793000000", text)

    def test_duplicates_once_earliest_expiry(self):
        toml = self.TOML + '[[subscriptions]]\nname = "Eweka"\nkind = "Usenet provider"\nexpires = 2026-12-01\n[[subscriptions]]\nname = "MAM VIP"\nkind = "MyAnonamouse class"\nexpires = 2027-03-01\n'
        text = ex.subscription_lines(toml, {"vip_expires": "2027-01-27"}, 1)
        self.assertEqual(text.count('{name="Eweka",kind="Usenet provider"}'), 1)
        self.assertEqual(text.count('{name="MAM VIP",kind="MyAnonamouse class"}'), 1)
        self.assertIn(f'subscription_expiry_timestamp_seconds{{name="Eweka",kind="Usenet provider"}} {int(ex.local_midnight(dt.date(2026, 11, 18)))}', text)
        self.assertIn(f'subscription_expiry_timestamp_seconds{{name="MAM VIP",kind="MyAnonamouse class"}} {int(ex.local_midnight(dt.date(2027, 1, 27)))}', text)

    def test_no_vip(self):
        self.assertNotIn("MAM VIP", ex.subscription_lines(self.TOML, {"vip_expires": ""}, 1))


class Indexers(unittest.TestCase):
    USAGE = {"ok": True, "generated": "2026-10-29T00:28:03Z", "indexers": [
        {"name": "MAM", "searches": {"used": 10, "limit": 100}, "downloads": {"used": 2, "limit": None}},
        {"name": "Other \"x\"", "searches": {"used": 5, "limit": None}}]}

    def test_lines(self):
        text = ex.indexer_lines(self.USAGE, "fastpi")
        self.assertIn('indexer_used{host="fastpi",indexer="MAM",kind="searches"} 10', text)
        self.assertIn('indexer_limit{host="fastpi",indexer="MAM",kind="searches"} 100', text)
        self.assertNotIn('indexer_limit{host="fastpi",indexer="MAM",kind="downloads"}', text)
        self.assertIn('indexer_used{host="fastpi",indexer="Other \\"x\\"",kind="searches"} 5', text)
        self.assertIn('indexer_bar_ok{host="fastpi"} 1', text)
        self.assertIn('indexer_bar_generated_timestamp_seconds{host="fastpi"} 1793233683', text)


if __name__ == "__main__":
    unittest.main()
