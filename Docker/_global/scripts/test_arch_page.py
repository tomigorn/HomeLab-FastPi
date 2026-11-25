#!/usr/bin/env python3
"""Tests for arch_page.py. Run: python3 test_arch_page.py"""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import arch_page as ap

INSPECT = [{
    "Name": "/notes", "State": {"Status": "running"},
    "Config": {"Image": "caddy:2.10-alpine", "Labels": {"com.docker.compose.project.working_dir": "/home/pi/Projects/Docker/Notes",
                                                         "org.opencontainers.image.version": "2.10.0"},
               "Env": ["NOTES_SECRET=hunter2", "OIDC_CLIENT_ID=abc"], "Healthcheck": {"Test": ["CMD", "true"]}},
    "HostConfig": {"NetworkMode": "notes_default"},
    "NetworkSettings": {"Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8099"}], "443/tcp": None},
                        "Networks": {"traefik_home": {"IPAddress": "10.24.22.9", "IPAMConfig": {"IPv4Address": "10.24.22.9"}, "Aliases": ["notes"]}}},
    "Mounts": [{"Type": "bind", "Source": "/home/pi/notes/www", "RW": False},
               {"Type": "bind", "Source": "/home/pi/Projects/Docker/Notes/data", "RW": True},
               {"Type": "bind", "Source": "/var/run/docker.sock", "RW": True}],
}, {
    "Name": "/dyn", "State": {"Status": "running"},
    "Config": {"Image": "x/y:1", "Labels": {"com.docker.compose.project": "dyn"}, "Env": []},
    "HostConfig": {"NetworkMode": "bridge"},
    "NetworkSettings": {"Ports": {}, "Networks": {"bridge": {"IPAddress": "172.17.0.2"}}},
    "Mounts": [{"Type": "volume", "Name": "v1", "Source": "/var/lib/docker/volumes/v1/_data", "RW": True}],
}]

TRAEFIK = '''http:
  routers:
    notes-outpost:
      rule: "Host(`notes.holy-grail.ch`) && PathPrefix(`/outpost.goauthentik.io/`)"
      service: authentik@file
    notes:
      rule: "Host(`notes.holy-grail.ch`)"
      service: notes
      middlewares:
        - authentik@file
        - default-rate-limit@file
    lan:
      rule: >-
        Host(`dyn.holy-grail.ch`)
        || Host(`dyn2.holy-grail.ch`)
      service: dyn
      middlewares: ["local-networks@file"]
  middlewares:
    x:
      headers: {}
  services:
    notes:
      loadBalancer:
        servers:
          - url: "http://notes:80"
    dyn:
      loadBalancer:
        servers:
          - url: "http://192.168.1.2:9000"
'''

CONF = "# c\nauto Notes - - -\nnotify grafana a,b - -\nedge-auto adguard - - -\n"
BK = ap.parse_backup_list("path /home/pi/Projects\npath /var/lib/docker/volumes/v1/_data\nexclude /home/pi/Projects/Docker/*/data\nsqlite /x\n")


class Inspect(unittest.TestCase):
    def setUp(self):
        self.rows = {r["name"]: r for r in ap.parse_inspect(INSPECT)}

    def test_fields(self):
        r = self.rows["notes"]
        self.assertEqual((r["project"], r["image"], r["version"]), ("Notes", "caddy:2.10-alpine", "2.10.0"))
        self.assertEqual(r["ports"], ["8099/tcp"])
        self.assertEqual(r["nets"], [{"name": "traefik_home", "ip": "10.24.22.9", "pinned": True}])

    def test_no_env_values_kept(self):
        self.assertNotIn("hunter2", json.dumps(self.rows))
        self.assertTrue(self.rows["notes"]["oidc_env"])

    def test_shared_netns(self):
        a = {"Id": "abc123456789xyz", "Name": "/gluetun", "Config": {"Image": "g"}, "HostConfig": {"NetworkMode": "bridge"}, "NetworkSettings": {}}
        b = {"Id": "def", "Name": "/qb", "Config": {"Image": "q"}, "HostConfig": {"NetworkMode": "container:abc123456789xyz"}, "NetworkSettings": {}}
        rows = {r["name"]: r for r in ap.parse_inspect([a, b])}
        self.assertEqual(rows["qb"]["shares_net"], "gluetun")
        self.assertEqual(ap.row_cells(rows["qb"], {}, {}, None)[3], "shares netns of gluetun")

    def test_flags(self):
        self.assertEqual(ap.flags(self.rows["notes"]), "")
        self.assertEqual(ap.flags(self.rows["dyn"]), "!ip !hc")


class Traefik(unittest.TestCase):
    def setUp(self):
        r, s = ap.parse_traefik_file(TRAEFIK)
        self.table = ap.route_table(r, s)
        self.rows = {r["name"]: r for r in ap.parse_inspect(INSPECT)}

    def test_forward_auth_by_container_name(self):
        routes = ap.routes_for(self.rows["notes"], self.table)
        self.assertEqual([x["host"] for x in routes], ["notes.holy-grail.ch"])
        self.assertEqual(ap.sso_label(routes, True), "forward-auth")

    def test_multiline_rule_and_host_port_upstream(self):
        d = {"name": "dyn", "aliases": [], "nets": [], "ports": ["9000/tcp"]}
        routes = ap.routes_for(d, self.table, "192.168.1.2")
        self.assertEqual([x["host"] for x in routes], ["dyn.holy-grail.ch", "dyn2.holy-grail.ch"])
        self.assertEqual(ap.sso_label(routes, False), "no forward-auth (LAN/VPN only)")

    def test_idp(self):
        self.assertEqual(ap.sso_label([], True, "Authentik"), "IdP")

    def test_no_route(self):
        self.assertEqual(ap.sso_label([], False), "-")
        self.assertEqual(ap.sso_label([], True), "own OIDC")


class UpdateAndBackup(unittest.TestCase):
    def test_tiers(self):
        t = ap.parse_update_conf(CONF)
        self.assertEqual(ap.tier_for("Notes", t), "auto")
        self.assertEqual(ap.tier_for("grafana", t), "notify")
        self.assertEqual(ap.tier_for("LanguageTool/Raspi", t), "manual")
        self.assertEqual(ap.tier_for("adguard", t), "edge-auto")

    def test_backup_states(self):
        rows = {r["name"]: r for r in ap.parse_inspect(INSPECT)}
        self.assertEqual(ap.backup_state(rows["dyn"], BK), "yes")
        self.assertEqual(ap.backup_state(rows["notes"], BK), "no")  # data/ is excluded, docker.sock and ro mount ignored
        self.assertEqual(ap.backup_state(rows["dyn"], None), "unknown")
        self.assertEqual(ap.backup_state(rows["dyn"], BK, {"dyn"}), "yes (dump)")

    def test_dumped(self):
        self.assertEqual(ap.dumped_containers("docker exec authentik-postgresql sh -c 'pg_dump -U x'"), {"authentik-postgresql"})


class Render(unittest.TestCase):
    def test_row_and_page(self):
        r, s = ap.parse_traefik_file(TRAEFIK)
        table = ap.route_table(r, s)
        rows = ap.parse_inspect(INSPECT)
        cells = [ap.row_cells(x, table, ap.parse_update_conf(CONF), BK) for x in rows]
        self.assertEqual(cells[1][:3], ["Notes", "notes", "caddy:2.10-alpine (2.10.0)"])
        self.assertEqual(cells[1][4:], ["8099/tcp", "notes.holy-grail.ch", "forward-auth", "no", "auto", ""])
        page = ap.render(dt.datetime(2026, 11, 25, 9, 0), {"intro": "Live.", "cells": cells}, {"intro": "asleep", "cells": []}, None)
        self.assertIn("## fastpi", page)
        self.assertIn("2 containers, 1 flagged", page)
        self.assertIn("## beefy\n\nasleep", page)
        self.assertNotIn("hunter2", page)


class Drift(unittest.TestCase):
    D = {"fastpi": {"updated": 1795617199, "items": [{"kind": "compose", "path": "mouse/sabnzbd", "detail": "config-hash: repo compose changed"}, {"kind": "unit", "path": "/etc/x|y.service", "detail": "no repo source"}]},
         "beefy": {"updated": 1795617244, "items": []}}

    def test_section_lists_items_per_host(self):
        s = ap.drift_section(self.D, {"beefy": False})
        self.assertIn("## Drift (repo vs live)", s)
        self.assertIn("| fastpi | compose | mouse/sabnzbd | config-hash: repo compose changed |", s)
        self.assertIn("/etc/x\\|y.service", s)
        self.assertIn("fastpi 2, beefy 0", s)

    def test_section_without_data_and_cached_beefy(self):
        self.assertIn("No data", ap.drift_section({}, {}))
        self.assertIn("(cached, host asleep)", ap.drift_section(self.D, {"beefy": True}))

    def test_page_has_the_section(self):
        page = ap.render(dt.datetime(2026, 11, 25, 9, 0), {"intro": "Live.", "cells": []}, None, None, self.D)
        self.assertIn("## Drift (repo vs live)", page)

    def test_remote_split_and_cache_carry_drift(self):
        out = "#UPTIME\nup\n#INSPECT\n[]\n#CONF\n#BACKUP\n#DUMP\n#DRIFT\n" + json.dumps(self.D["beefy"]) + "\n"
        self.assertEqual(json.loads(ap.split_remote(out)["DRIFT"]), self.D["beefy"])


class Tower(unittest.TestCase):
    def test_stack(self):
        sh = 'NET="nc"\nHTTP_PORT="8080"\nNC_IMAGE="nextcloud:stable"\ndocker run -d \\\n  --name nc \\\n  --network "$NET" \\\n  -p "${HTTP_PORT}:80" \\\n  -v "/a:/b" \\\n  -e PASS="$SECRET" \\\n  "$NC_IMAGE" >/dev/null\n'
        c = ap.parse_tower_stack(sh, "nextcloud")[0]
        self.assertEqual((c["name"], c["image"], c["net"], c["ports"], c["healthcheck"]), ("nc", "nextcloud:stable", "nc", ["8080/tcp"], False))


class BeefyCache(unittest.TestCase):
    def test_asleep_uses_cache_then_none(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "c" / "beefy.json"
            now = dt.datetime(2026, 11, 25, 4, 35)
            def down(cmd, t):
                raise OSError("no route")
            self.assertEqual(ap.collect_beefy(now, down, cache), (None, False))
            out = "#UPTIME\nup 1 hour\n#INSPECT\n" + json.dumps(INSPECT) + "\n#CONF\nauto Notes - - -\n#BACKUP\npath /home/pi/Projects\n#DUMP\ndocker exec dyn sh -c 'pg_dump x'\n"
            class P: returncode = 0; stdout = out
            data, fresh = ap.collect_beefy(now, lambda c, t: P(), cache)
            self.assertTrue(fresh)
            self.assertEqual(len(data["rows"]), 2)
            self.assertEqual(data["dumped"], ["dyn"])
            data, fresh = ap.collect_beefy(now, down, cache)
            self.assertFalse(fresh)
            self.assertEqual(data["as_of"], "2026-11-25T04:35")
            self.assertNotIn("hunter2", cache.read_text())


if __name__ == "__main__":
    unittest.main()
