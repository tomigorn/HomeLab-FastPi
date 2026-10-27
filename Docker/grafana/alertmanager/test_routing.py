#!/usr/bin/env python3
"""Routing and quiet hours of alertmanager.yml(.example).   python3 test_routing.py [config]

Receivers come from `amtool config routes test` (the real router); which route matched and whether it is muted 22:00-07:00 Europe/Zurich is checked here, because amtool does not evaluate time intervals.
"""
import datetime as dt
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

HERE = Path(__file__).resolve().parent
CONFIG = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 else HERE / "alertmanager.yml.example"
IMAGE = "quay.io/prometheus/alertmanager:v0.34.1"
ZRH = ZoneInfo("Europe/Zurich")

# labels, receiver, muted in quiet hours
CASES = [
    ({"alertname": "DeadMansSwitch", "severity": "deadman"}, "healthchecks", False),
    ({"alertname": "AlertingHeartbeat", "severity": "heartbeat"}, "heartbeat", False),
    ({"alertname": "PublicEndpointDown", "severity": "critical"}, "critical", False),
    ({"alertname": "AutoUpdateRollbackFailed", "severity": "critical", "host": "beefy"}, "critical", False),
    ({"alertname": "MalwareQuarantined", "severity": "warning", "host": "beefy"}, "malware", False),
    ({"alertname": "MalwareFound", "severity": "warning", "host": "fastpi"}, "telegram-and-email", False),
    ({"alertname": "ContainerDown", "severity": "warning", "name": "traefik"}, "telegram-and-email", False),
    ({"alertname": "ContainerDown", "severity": "warning", "name": "authentik-server"}, "telegram-and-email", False),
    ({"alertname": "ContainerDown", "severity": "warning", "name": "jellyfin"}, "telegram", True),
    ({"alertname": "ContainerCrashLooping", "severity": "warning", "name": "authentik-server"}, "telegram", True),
    ({"alertname": "SecurityFileChanged", "severity": "warning"}, "telegram", True),
    ({"alertname": "SshLoginOutsideLan", "severity": "warning", "source_class": "other"}, "telegram", True),
    ({"alertname": "SshLoginOutsideLan", "severity": "warning", "source_class": "vpn", "notify": "digest"}, "null", None),
    ({"alertname": "SecurityScanFailing", "severity": "warning", "notify": "digest"}, "null", None),
    ({"alertname": "NewFixableImageVulnerability", "severity": "info", "notify": "digest"}, "null", None),
    ({"alertname": "AutoUpdateNightly", "severity": "info", "notify": "digest"}, "null", None),
    ({"alertname": "HostFilesystemSpaceLow", "severity": "warning", "notify": "digest"}, "null", None),
    ({"alertname": "ContainerImageUpdatesAvailable", "severity": "info", "notify": "weekly"}, "null", None),
    ({"alertname": "UnraidUpdateAvailable", "severity": "info", "notify": "weekly"}, "null", None),
    ({"alertname": "DailyDigest", "severity": "info"}, "telegram-digest", False),
    ({"alertname": "WeeklyUpdateDigest", "severity": "info"}, "telegram-digest", False),
    ({"alertname": "BeefyAwakeLong", "severity": "warning"}, "telegram-beefy-awake", True),
    ({"alertname": "BeefyWakeLoop", "severity": "warning"}, "telegram", True),
    ({"alertname": "RootkitWarning", "severity": "info"}, "telegram", True),
    ({"alertname": "SecurityScanStale", "severity": "warning", "subject": "av-tower"}, "telegram", True),
    ({"alertname": "AlertNotificationsFailing", "severity": "info", "integration": "telegram"}, "email", False),
    ({"alertname": "AlertNotificationsFailing", "severity": "info", "integration": "email"}, "telegram", True),
    ({"alertname": "HostRebootedUnclean", "severity": "warning"}, "telegram", True),
    ({"alertname": "MalwareQuarantined", "severity": "warning", "host": "fastpi", "test": "eicar"}, "telegram-test", False),
    ({"alertname": "SyntheticCheck", "severity": "critical", "test": "batch"}, "telegram-test", False),
]

MAIL_RECEIVERS = {"critical", "telegram-and-email", "malware", "heartbeat", "email"}


def matches(matcher: str, labels: dict) -> bool:
    name, op, value = re.match(r'(\w+)(=~|!~|!=|=)"?(.*?)"?$', matcher).groups()
    v = labels.get(name, "")
    if op == "=":
        return v == value
    if op == "!=":
        return v != value
    full = re.fullmatch(value, v) is not None
    return full if op == "=~" else not full


def route_for(route: dict, labels: dict) -> dict:
    for child in route.get("routes", []):
        if all(matches(m, labels) for m in child.get("matchers", [])):
            return route_for(child, labels) if child.get("routes") else child
    return route


def in_interval(intervals: list, when: dt.datetime) -> bool:
    for ti in intervals:
        local = when.astimezone(ZoneInfo(ti.get("location", "UTC")))
        minute = local.hour * 60 + local.minute
        for t in ti.get("times", []):
            start, end = (int(x[:2]) * 60 + int(x[3:]) for x in (t["start_time"], t["end_time"]))
            if start <= minute < end:
                return True
    return False


class Routing(unittest.TestCase):
    cfg = yaml.safe_load(CONFIG.read_text())

    def muted(self, labels: dict, when: dt.datetime) -> bool:
        names = route_for(self.cfg["route"], labels).get("mute_time_intervals", [])
        named = {t["name"]: t["time_intervals"] for t in self.cfg.get("time_intervals", [])}
        return any(in_interval(named[n], when) for n in names)

    def test_receivers_by_amtool(self):
        script = "".join(
            f"amtool config routes test --config.file=/c.yml --verify.receivers={rcv} "
            + " ".join(f"'{k}={v}'" for k, v in labels.items()) + f" >/dev/null || echo 'MISMATCH {rcv} {labels}'; "
            for labels, rcv, _ in CASES)
        r = subprocess.run(["docker", "run", "--rm", "--network", "none", "--user", f"{os.getuid()}", "--entrypoint", "sh",
                            "-v", f"{CONFIG}:/c.yml:ro", IMAGE, "-c", script], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "", r.stdout + r.stderr)

    def test_python_router_agrees(self):
        for labels, rcv, _ in CASES:
            self.assertEqual(route_for(self.cfg["route"], labels).get("receiver", self.cfg["route"]["receiver"]), rcv, labels)

    def test_quiet_hours_both_seasons(self):
        for day in ("2026-01-15", "2026-07-15"):
            for hhmm, quiet in (("21:59", False), ("22:00", True), ("03:00", True), ("06:59", True), ("07:00", False), ("12:00", False)):
                when = dt.datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=ZRH)
                for labels, rcv, muted in CASES:
                    if muted is None:
                        continue
                    self.assertEqual(self.muted(labels, when), muted and quiet, (day, hhmm, labels))

    def test_mail_only_for_critical_malware_heartbeat_edge(self):
        mailed = {r for _, r, _ in CASES} & MAIL_RECEIVERS
        for labels, rcv, _ in CASES:
            if rcv in mailed and "test" not in labels:
                self.assertTrue(labels.get("severity") in ("critical", "heartbeat") or labels["alertname"].startswith("Malware")
                                or labels["alertname"] in ("ContainerDown", "AlertNotificationsFailing"), labels)

    def test_resolved_only_for_critical(self):
        for r in self.cfg["receivers"]:
            for kind in ("email_configs", "telegram_configs", "webhook_configs"):
                for c in r.get(kind, []):
                    self.assertEqual(c.get("send_resolved", True), r["name"] == "critical", (r["name"], kind))

    def test_no_mute_on_root(self):
        self.assertNotIn("mute_time_intervals", self.cfg["route"])


if __name__ == "__main__":
    unittest.main()
