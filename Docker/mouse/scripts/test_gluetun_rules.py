#!/usr/bin/env python3
"""The gluetun firewall rules must survive Docker swapping eth0 and eth1 on a restart. python3 test_gluetun_rules.py"""
import re
import unittest
from pathlib import Path

import yaml

MOUSE = Path(__file__).resolve().parent.parent
RULES = (MOUSE / "gluetun" / "post-rules.txt").read_text()
COMPOSE = yaml.safe_load((MOUSE / "docker-compose.yaml").read_text())


class Rules(unittest.TestCase):
    def test_no_custom_chain(self):
        # gluetun parses INPUT to remove its forwarded-port rule and crashes on a jump to an unknown target.
        self.assertNotIn("iptables -N", RULES)
        for line in RULES.splitlines():
            if line.startswith("iptables") and " -j " in line:
                self.assertIn(line.split(" -j ")[1].split()[0], {"ACCEPT", "DROP", "REJECT"}, line)

    def test_no_rule_names_a_docker_interface(self):
        self.assertIsNone(re.search(r"\beth\d\b", RULES))

    def test_allow_list_is_bound_to_the_traefik_address(self):
        ip = COMPOSE["services"]["gluetun"]["networks"]["traefik_mouse"]["ipv4_address"]
        self.assertIn(f"iptables -I INPUT 1 -d {ip} -m conntrack --ctstate NEW -j DROP", RULES)
        allows = [l for l in RULES.splitlines() if l.startswith(f"iptables -I INPUT 1 -d {ip} -s ")]
        self.assertEqual(len(allows), 6, "one rule per source and port, no multiport")
        self.assertGreater(RULES.index(allows[0]), RULES.index(f"iptables -I INPUT 1 -d {ip} -m conntrack --ctstate NEW -j DROP"),
                           "the DROP must be inserted first so the allows end up above it")


if __name__ == "__main__":
    unittest.main(verbosity=1)
