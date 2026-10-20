#!/usr/bin/env python3
"""Tests for the pure parts of container_exporter.py.   python3 test_container_exporter.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import container_exporter as ex  # noqa: E402

NOW = ex.parse_ts("2026-10-20T03:00:00Z")


def c(name, status="running", policy="unless-stopped", health=None, restarts=0,
      started="2026-10-20T02:00:00.123456789Z", project="infra__traefik", cid=None):
    state = {"Status": status, "Running": status == "running", "StartedAt": started}
    if health:
        state["Health"] = {"Status": health}
    return {"Id": cid or name * 4, "Name": "/" + name, "RestartCount": restarts, "State": state,
            "HostConfig": {"RestartPolicy": {"Name": policy}},
            "Config": {"Labels": {"com.docker.compose.project": project} if project else {}}}


class Rows(unittest.TestCase):
    def test_expected_follows_restart_policy_and_manual_stop(self):
        rows = {r["name"]: r for r in ex.rows([
            c("traefik"), c("cloudflared", policy="always"), c("crashed", status="exited"),
            c("stopped", status="exited", cid="s1"), c("oneshot", status="exited", policy="no"),
            c("failing", status="exited", policy="on-failure")], manually_stopped={"s1"})}
        self.assertEqual({n: r["expected"] for n, r in rows.items()},
                         {"traefik": 1, "cloudflared": 1, "crashed": 1, "stopped": 0, "oneshot": 0, "failing": 0})
        self.assertEqual(rows["crashed"]["running"], 0)
        self.assertEqual(rows["traefik"]["running"], 1)

    def test_created_and_restarting_are_not_running(self):
        rows = {r["name"]: r for r in ex.rows([c("a", status="created"), c("b", status="restarting")], set())}
        self.assertEqual((rows["a"]["running"], rows["b"]["running"]), (0, 0))
        self.assertEqual((rows["a"]["expected"], rows["b"]["expected"]), (1, 1))

    def test_health_restarts_started_project(self):
        r = ex.rows([c("x", health="unhealthy", restarts=53, project=None)], set())[0]
        self.assertEqual((r["unhealthy"], r["restarts"], r["project"]), (1, 53, ""))
        self.assertEqual(r["started"], ex.parse_ts("2026-10-20T02:00:00Z"))
        self.assertIsNone(ex.rows([c("y")], set())[0]["unhealthy"])
        self.assertEqual(ex.rows([c("z", health="healthy")], set())[0]["unhealthy"], 0)

    def test_stopped_container_keeps_no_stale_health(self):
        self.assertIsNone(ex.rows([c("v", status="exited", policy="no", health="unhealthy")], set())[0]["unhealthy"])

    def test_never_started_has_no_start_time(self):
        self.assertIsNone(ex.rows([c("n", status="created", started="0001-01-01T00:00:00Z")], set())[0]["started"])


class Render(unittest.TestCase):
    def test_metrics(self):
        out = ex.render(ex.rows([c("traefik", health="healthy", restarts=2), c("vault", status="exited", policy="no", project="")], set()),
                        unclean=1)
        self.assertIn('container_expected_running{name="traefik",project="infra__traefik"} 1', out)
        self.assertIn('container_running{name="vault",project=""} 0', out)
        self.assertIn('container_restart_count{name="traefik",project="infra__traefik"} 2', out)
        self.assertIn('container_unhealthy{name="traefik",project="infra__traefik"} 0', out)
        self.assertNotIn('container_unhealthy{name="vault"', out)
        self.assertIn('container_started_timestamp_seconds{name="traefik",project="infra__traefik"} 1792461600', out)
        self.assertIn("host_last_boot_unclean 1", out)
        self.assertEqual(out.count("# TYPE container_running gauge"), 1)


class Unclean(unittest.TestCase):
    def test_journald_replaced_a_dirty_journal(self):
        self.assertTrue(ex.boot_was_unclean(
            "systemd-journald[345]: File /var/log/journal/x/system.journal corrupted or uncleanly shut down, renaming and replacing."))
        self.assertFalse(ex.boot_was_unclean("systemd-journald[345]: Journal started"))


class Watchdog(unittest.TestCase):
    """Prometheus or Alertmanager down: nothing else can alert, so the exporter tells Telegram itself."""

    def test_quiet_until_down_for_ten_minutes_then_once(self):
        s = {}
        self.assertIsNone(ex.watchdog(s, NOW, {"prometheus": False, "alertmanager": True}))
        self.assertIsNone(ex.watchdog(s, NOW + 540, {"prometheus": False, "alertmanager": True}))
        msg = ex.watchdog(s, NOW + 600, {"prometheus": False, "alertmanager": True})
        self.assertIn("prometheus", msg)
        self.assertIsNone(ex.watchdog(s, NOW + 660, {"prometheus": False, "alertmanager": True}))
        self.assertIn("back", ex.watchdog(s, NOW + 900, {"prometheus": True, "alertmanager": True}))
        self.assertIsNone(ex.watchdog(s, NOW + 960, {"prometheus": True, "alertmanager": True}))

    def test_short_blip_sends_nothing(self):
        s = {}
        ex.watchdog(s, NOW, {"prometheus": False, "alertmanager": False})
        self.assertIsNone(ex.watchdog(s, NOW + 120, {"prometheus": True, "alertmanager": True}))
        self.assertEqual(s, {"down_since": {}, "notified": []})

    def test_unsent_alert_is_retried(self):
        s = {}
        ex.watchdog(s, NOW, {"prometheus": False, "alertmanager": True})
        self.assertIsNotNone(ex.watchdog(s, NOW + 600, {"prometheus": False, "alertmanager": True}))
        ex.watchdog_failed(s, "prometheus")
        self.assertIsNotNone(ex.watchdog(s, NOW + 660, {"prometheus": False, "alertmanager": True}))


class ChatId(unittest.TestCase):
    def test_reads_first_chat_id(self):
        self.assertEqual(ex.chat_id("receivers:\n  - name: x\n    telegram_configs:\n        chat_id: -1001234567890   # c\n"),
                         "-1001234567890")
        self.assertIsNone(ex.chat_id("receivers: []"))


if __name__ == "__main__":
    unittest.main()
