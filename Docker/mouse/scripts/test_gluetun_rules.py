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
    def test_no_rule_names_a_docker_interface(self):
        self.assertIsNone(re.search(r"\beth\d\b", RULES))

    def test_allow_list_is_bound_to_the_traefik_address(self):
        ip = COMPOSE["services"]["gluetun"]["networks"]["traefik_mouse"]["ipv4_address"]
        self.assertIn(f"iptables -I INPUT 1 -d {ip} -m conntrack --ctstate NEW -j MOUSE-TRAEFIK", RULES)

    def test_allow_list_ends_in_drop(self):
        chain = [l for l in RULES.splitlines() if l.startswith("iptables -A MOUSE-TRAEFIK")]
        self.assertEqual(chain[-1], "iptables -A MOUSE-TRAEFIK -j DROP")
        self.assertEqual(len(chain), 4)


if __name__ == "__main__":
    unittest.main(verbosity=1)
