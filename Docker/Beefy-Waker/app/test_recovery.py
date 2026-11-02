#!/usr/bin/env python3
"""Tests for the Beefy-Waker wake-recovery state machine (fake clock, plug, probe)."""
import http.server
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from recovery import MyStromPlug, Recovery, post_alert, write_textfile


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakePlug:
    def __init__(self):
        self.relay_state = True
        self.fail_set = False
        self.stuck_on = False
        self.readback_none = False
        self.raise_on = None
        self.unreachable = False
        self.calls = []

    def relay(self):
        self.calls.append(("relay",))
        if self.raise_on == "relay":
            raise OSError("boom")
        if self.readback_none and self.calls.count(("set", False)):
            return None
        return None if self.unreachable else self.relay_state

    def set(self, on):
        self.calls.append(("set", on))
        if self.raise_on == "set":
            raise OSError("boom")
        if self.stuck_on and not on:
            return True
        if self.unreachable or self.fail_set:
            return False
        self.relay_state = on
        return True

    def power(self):
        return 42.0

    def sets(self):
        return [c[1] for c in self.calls if c[0] == "set"]


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.plug = FakePlug()
        self.up_from = {}
        self.wols = []
        self.alerts = []
        self.snaps = []
        self.probe_log = []
        self.metrics_fail = False
        self.alert_fail = False
        self.rec = Recovery(
            probe=self._probe,
            send_wol=lambda: self.wols.append(self.clock.now),
            plug=self.plug,
            alert=self._alert,
            write_metrics=self._metrics,
            clock=self.clock,
            wall=lambda: 1000.0 + self.clock.now,
        )

    def _probe(self, port):
        self.probe_log.append((self.clock.now, port))
        return port in self.up_from and self.clock.now >= self.up_from[port]

    def _alert(self, *a):
        self.alerts.append(a)
        if self.alert_fail:
            raise OSError("alert down")

    def _metrics(self, snap):
        if self.metrics_fail:
            raise OSError("disk full")
        self.snaps.append(snap)

    def run_to(self, t):
        while self.clock.now < t:
            self.clock.now += 1
            self.rec.step()

    def phase(self):
        return self.rec.status()["phase"]

    def to_broken_no_boot(self):
        self.rec.start(8096, True, "jane", "Jellyfin")
        self.run_to(285)

    def test_normal_wake_ends_idle_without_alert(self):
        self.up_from = {22: 40, 8096: 40}
        self.rec.start(8096, True, "jane", "Jellyfin")
        self.run_to(39)
        self.assertEqual(self.phase(), "waking")
        self.run_to(45)
        self.assertEqual(self.phase(), "idle")
        self.assertEqual(self.alerts, [])
        self.assertEqual(self.plug.calls, [])

    def test_unarmed_never_escalates(self):
        self.rec.start(22, False)
        self.run_to(299)
        self.assertEqual(self.phase(), "waking")
        self.run_to(400)
        self.assertEqual(self.phase(), "idle")
        self.assertEqual(self.plug.calls, [])
        self.assertEqual(self.alerts, [])
        self.assertEqual(self.rec.snapshot()["failures"], {r: 0 for r in ("no_boot", "service_down", "plug_off", "plug_unreachable")})
        self.assertTrue(14 <= len(self.wols) <= 16)
        self.assertLessEqual(max(self.wols), 300)

    def test_armed_no_answer_power_cycles_at_t1(self):
        self.rec.start(8096, True, "jane", "Jellyfin")
        self.run_to(119)
        self.assertEqual(self.phase(), "waking")
        self.assertEqual(self.plug.sets(), [])
        self.run_to(120)
        self.assertEqual(self.plug.sets(), [False])
        self.run_to(134)
        self.assertEqual(self.plug.sets(), [False])
        self.run_to(135)
        self.assertEqual(self.plug.sets(), [False, True])
        self.run_to(140)
        self.assertEqual(self.phase(), "retrying")
        self.assertEqual(self.wols[-1], 140)
        self.assertEqual(self.rec.snapshot()["power_cycles"], 1)

    def test_recovers_after_power_cycle(self):
        self.up_from = {22: 200}
        self.rec.start(8096, True, "jane", "Jellyfin")
        self.run_to(205)
        self.assertEqual(self.phase(), "idle")
        self.assertEqual(len(self.alerts), 1)
        self.assertEqual(self.alerts[0][0], "BeefyWakeRecovered")
        self.assertEqual(self.alerts[0][1], "info")
        self.assertEqual(self.rec.snapshot()["recoveries"]["power_cycle"], 1)

    def test_no_boot_after_power_cycle_breaks(self):
        self.to_broken_no_boot()
        self.assertEqual(self.phase(), "broken")
        self.assertEqual(self.rec.status()["reason"], "no_boot")
        self.assertEqual(len(self.alerts), 1)
        self.assertEqual(self.alerts[0][:2], ("BeefyWakeFailed", "critical"))
        self.assertIn("jane", self.alerts[0][3])
        self.assertIn("Jellyfin", self.alerts[0][3])
        self.assertIn("42", self.alerts[0][3])
        self.assertEqual(self.rec.snapshot()["failures"]["no_boot"], 1)

    def test_not_broken_one_second_early(self):
        self.rec.start(8096, True)
        self.run_to(284)
        self.assertEqual(self.phase(), "retrying")

    def test_service_port_answer_blocks_power_cut(self):
        self.up_from = {8096: 120}
        self.rec.start(8096, True, "jane", "Jellyfin")
        self.run_to(130)
        self.assertEqual(self.plug.sets(), [])
        self.assertEqual(self.phase(), "idle")
        self.assertEqual(self.alerts, [])

    def test_host_up_service_down_alarms_without_power_cut(self):
        self.up_from = {22: 40}
        self.rec.start(5055, True, "jane", "Seerr")
        self.run_to(299)
        self.assertEqual(self.phase(), "waking")
        self.run_to(300)
        self.assertEqual(self.phase(), "broken")
        self.assertEqual(self.rec.status()["reason"], "service_down")
        self.assertEqual(self.plug.sets(), [])
        self.assertEqual(self.alerts[0][:2], ("BeefyWakeFailed", "critical"))

    def test_plug_off_on_purpose_not_switched_on(self):
        self.plug.relay_state = False
        self.rec.start(8096, True)
        self.run_to(130)
        self.assertEqual(self.plug.sets(), [])
        self.assertEqual(self.phase(), "broken")
        self.assertEqual(self.rec.status()["reason"], "plug_off")
        self.assertEqual(len(self.alerts), 1)

    def test_plug_unreachable_breaks(self):
        self.plug.unreachable = True
        self.rec.start(8096, True)
        self.run_to(125)
        self.assertEqual(self.phase(), "broken")
        self.assertEqual(self.rec.status()["reason"], "plug_unreachable")

    def test_plug_set_failure_breaks(self):
        self.plug.fail_set = True
        self.rec.start(8096, True)
        self.run_to(125)
        self.assertEqual(self.phase(), "broken")
        self.assertEqual(self.rec.status()["reason"], "plug_unreachable")
        self.assertEqual(len(self.alerts), 1)

    def test_unarmed_campaign_armed_by_join(self):
        self.rec.start(22, False)
        self.run_to(60)
        self.rec.start(8096, True, "jane", "Jellyfin")
        self.run_to(119)
        self.assertEqual(self.phase(), "waking")
        self.run_to(120)
        self.assertEqual(self.phase(), "power_cycle")
        self.assertEqual(self.plug.sets(), [False])

    def test_broken_latch_blocks_second_cycle(self):
        self.to_broken_no_boot()
        sets = list(self.plug.sets())
        self.run_to(385)
        n = len(self.wols)
        self.rec.start(8096, True, "jane", "Jellyfin")
        self.assertEqual(len(self.wols), n + 1)
        self.run_to(600)
        self.assertEqual(self.phase(), "broken")
        self.assertEqual(self.plug.sets(), sets)
        self.assertEqual(len(self.alerts), 1)

    def test_latch_expires_after_6h(self):
        self.to_broken_no_boot()
        self.run_to(285 + 21599)
        self.assertEqual(self.phase(), "broken")
        self.run_to(285 + 21600)
        self.assertEqual(self.phase(), "idle")
        self.assertEqual(len(self.alerts), 1)
        t = self.clock.now
        self.rec.start(8096, True)
        self.run_to(t + 120)
        self.assertEqual(self.plug.sets().count(False), 2)

    def test_broken_watcher_detects_recovery(self):
        self.to_broken_no_boot()
        self.up_from = {22: 285 + 600}
        self.run_to(285 + 630)
        self.assertEqual(self.phase(), "idle")
        self.assertEqual([a[0] for a in self.alerts], ["BeefyWakeFailed", "BeefyWakeRecovered"])
        self.assertEqual(self.rec.snapshot()["recoveries"]["broken"], 1)

    def test_status_seconds_left(self):
        self.assertEqual(self.rec.status(), {"phase": "idle", "seconds_left": None, "reason": ""})
        self.rec.start(8096, True)
        self.run_to(30)
        self.assertEqual(self.rec.status()["seconds_left"], 90)
        self.assertTrue(self.rec.in_progress())
        self.run_to(145)
        self.assertEqual(self.phase(), "retrying")
        self.assertEqual(self.rec.status()["seconds_left"], 140)
        self.run_to(285)
        self.assertIsNone(self.rec.status()["seconds_left"])
        self.assertFalse(self.rec.in_progress())

    def test_status_unarmed_has_no_deadline(self):
        self.rec.start(22, False)
        self.run_to(30)
        self.assertIsNone(self.rec.status()["seconds_left"])

    def test_metrics_written_on_each_phase_change(self):
        self.to_broken_no_boot()
        phases = []
        for s in self.snaps:
            if not phases or phases[-1] != s["phase"]:
                phases.append(s["phase"])
        self.assertEqual(phases, ["waking", "power_cycle", "retrying", "broken"])

    def test_run_writes_idle_metrics_before_first_step(self):
        class Stop(BaseException):
            pass

        def step():
            raise Stop

        self.rec.step = step
        with self.assertRaises(Stop):
            self.rec.run()
        self.assertEqual([s["phase"] for s in self.snaps], ["idle"])

    def test_snapshot_counts(self):
        self.rec.start(22, False)
        self.rec.start(8096, True)
        snap = self.rec.snapshot()
        self.assertEqual(snap["campaigns"], {"0": 1, "1": 0})
        self.assertIn("campaign", snap["last"])


    def test_service_down_not_recovered_by_ssh_alone(self):
        self.up_from = {22: 40}
        self.rec.start(5055, True, "jane", "Seerr")
        self.run_to(400)
        self.assertEqual(self.phase(), "broken")
        self.assertEqual(len(self.alerts), 1)
        self.up_from[5055] = 500
        self.run_to(560)
        self.assertEqual(self.phase(), "idle")
        self.assertEqual([a[0] for a in self.alerts], ["BeefyWakeFailed", "BeefyWakeRecovered"])

    def test_metrics_failure_never_blocks_alert_or_cut(self):
        self.metrics_fail = True
        self.rec.start(8096, True, "jane", "Jellyfin")
        self.run_to(120)
        self.assertEqual(self.plug.sets(), [False])
        self.run_to(285)
        self.assertEqual(self.phase(), "broken")
        self.assertEqual(len(self.alerts), 1)

    def test_plug_exception_is_plug_unreachable(self):
        for which in ("relay", "set"):
            self.setUp()
            self.plug.raise_on = which
            self.rec.start(8096, True)
            self.run_to(125)
            self.assertEqual(self.phase(), "broken", which)
            self.assertEqual(self.rec.status()["reason"], "plug_unreachable", which)
            self.assertEqual(self.alerts[0][0], "BeefyWakeFailed")

    def test_alert_exception_swallowed_state_advances(self):
        self.alert_fail = True
        self.rec.start(8096, True)
        self.run_to(285)
        self.assertEqual(self.phase(), "broken")
        self.assertEqual(len(self.alerts), 1)

    def test_one_power_cycle_per_latch_even_after_recovery(self):
        self.up_from = {22: 200}
        self.rec.start(8096, True, "jane", "Jellyfin")
        self.run_to(205)
        self.assertEqual(self.phase(), "idle")
        self.up_from = {}
        self.clock.now = 3800
        self.rec.start(8096, True, "jane", "Jellyfin")
        self.run_to(3800 + 130)
        self.assertEqual(self.plug.sets(), [False, True])
        self.assertEqual(self.phase(), "broken")
        self.assertEqual(self.rec.status()["reason"], "no_boot")
        self.assertEqual([a[0] for a in self.alerts], ["BeefyWakeRecovered", "BeefyWakeFailed"])

    def test_probes_at_most_every_5s(self):
        self.rec.start(8096, True)
        self.run_to(100)
        times = [t for t, p in self.probe_log if p == 22]
        self.assertGreater(len(times), 10)
        self.assertTrue(all(b - a >= 5 for a, b in zip(times, times[1:])))

    def test_plug_left_on_when_off_readback_wrong(self):
        self.plug.stuck_on = True
        self.rec.start(8096, True)
        self.run_to(125)
        self.assertEqual(self.plug.sets(), [False, True])
        self.assertEqual(self.rec.status()["reason"], "plug_unreachable")

    def test_plug_left_on_when_off_readback_fails(self):
        self.plug.readback_none = True
        self.rec.start(8096, True)
        self.run_to(125)
        self.assertEqual(self.plug.sets(), [False, True])
        self.assertEqual(self.phase(), "broken")

    def test_seconds_left_during_service_wait(self):
        self.up_from = {22: 40}
        self.rec.start(5055, True)
        self.run_to(100)
        self.assertEqual(self.rec.status()["seconds_left"], 200)



class StubServer(http.server.BaseHTTPRequestHandler):
    relay_seq, reqs, report_status = [], [], 200

    def do_GET(self):
        type(self).reqs.append(("GET", self.path, b""))
        body = b"{}"
        if self.path.startswith("/report"):
            seq = type(self).relay_seq
            relay = seq.pop(0) if len(seq) > 1 else seq[0]
            body = json.dumps({"relay": relay, "power": 42.5}).encode()
        self._reply(body)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        type(self).reqs.append(("POST", self.path, raw))
        self._reply(b"{}")

    def _reply(self, body):
        self.send_response(type(self).report_status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class StubBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), StubServer)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        StubServer.relay_seq, StubServer.reqs, StubServer.report_status = [True], [], 200


def closed_port_url():
    s = ThreadingHTTPServer(("127.0.0.1", 0), StubServer)
    url = f"http://127.0.0.1:{s.server_address[1]}"
    s.server_close()
    return url


class MyStromPlugTest(StubBase):
    def plug(self, base=None):
        self.sleeps = []
        return MyStromPlug(base or self.base, timeout=1, sleep=self.sleeps.append)

    def test_relay_and_power(self):
        p = self.plug()
        self.assertIs(p.relay(), True)
        self.assertEqual(p.power(), 42.5)

    def test_plug_set_reads_back(self):
        StubServer.relay_seq = [False]
        p = self.plug()
        self.assertTrue(p.set(False))
        self.assertIn("/relay?state=0", [r[1] for r in StubServer.reqs])

    def test_plug_set_waits_for_slow_relay(self):
        StubServer.relay_seq = [True, True, False]
        self.assertTrue(self.plug().set(False))
        self.assertEqual(self.sleeps, [1, 1])

    def test_plug_set_false_when_relay_does_not_change(self):
        StubServer.relay_seq = [True]
        p = self.plug()
        self.assertFalse(p.set(False))
        self.assertEqual(sum(1 for r in StubServer.reqs if r[1].startswith("/report")), 3)

    def test_plug_unreachable_is_none(self):
        p = self.plug(closed_port_url())
        self.assertIsNone(p.relay())
        self.assertIsNone(p.power())
        self.assertFalse(p.set(True))

    def test_plug_http_error_is_none(self):
        StubServer.report_status = 500
        self.assertIsNone(self.plug().relay())


class PostAlertTest(StubBase):
    def test_post_alert_payload(self):
        ok = post_alert(self.base, "BeefyWakeFailed", "critical", "sum", "det", "desc", wall=lambda: 1767268800)
        self.assertTrue(ok)
        method, path, raw = StubServer.reqs[-1]
        self.assertEqual((method, path), ("POST", "/api/v2/alerts"))
        (a,) = json.loads(raw)
        self.assertEqual(set(a["labels"]), {"alertname", "host", "severity", "source", "at"})
        self.assertEqual(a["labels"]["alertname"], "BeefyWakeFailed")
        self.assertEqual(a["labels"]["host"], "beefy")
        self.assertEqual(a["labels"]["severity"], "critical")
        self.assertEqual(a["labels"]["source"], "beefy-waker")
        self.assertRegex(a["labels"]["at"], r"^\d{14}$")
        self.assertEqual(set(a["annotations"]), {"summary", "time", "details", "description"})
        self.assertEqual(a["annotations"]["summary"], "sum")
        self.assertEqual(a["annotations"]["details"], "det")
        self.assertEqual(a["annotations"]["description"], "desc")
        self.assertRegex(a["annotations"]["time"], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")
        self.assertRegex(a["startsAt"], r"^\d{4}-\d\d-\d\dT")
        self.assertRegex(a["endsAt"], r"^\d{4}-\d\d-\d\dT")
        self.assertNotEqual(a["startsAt"], a["endsAt"])

    def test_post_alert_never_raises(self):
        self.assertFalse(post_alert(closed_port_url(), "X", "info", "s", "d", "x"))

    def test_post_alert_http_error_is_false(self):
        StubServer.report_status = 500
        self.assertFalse(post_alert(self.base, "X", "info", "s", "d", "x"))


class TextfileTest(unittest.TestCase):
    SNAP = {"phase": "broken", "campaigns": {"0": 2, "1": 3}, "power_cycles": 1,
            "failures": {"no_boot": 1}, "recoveries": {"power_cycle": 4},
            "last": {"campaign": 1000.5, "failure": 2000.0}}

    def test_textfile_contents(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "beefy_wake.prom")
            write_textfile(path, self.SNAP)
            text = open(path).read()
            self.assertEqual(os.listdir(d), ["beefy_wake.prom"])
        for line in (
            'beefy_wake_phase{phase="broken"} 1', 'beefy_wake_phase{phase="idle"} 0',
            'beefy_wake_phase{phase="retrying"} 0', "beefy_wake_power_cycles_total 1",
            'beefy_wake_failures_total{reason="no_boot"} 1', 'beefy_wake_failures_total{reason="plug_off"} 0',
            'beefy_wake_campaigns_total{signed_in="1"} 3', 'beefy_wake_campaigns_total{signed_in="0"} 2',
            'beefy_wake_recoveries_total{after="power_cycle"} 4', 'beefy_wake_recoveries_total{after="broken"} 0',
            'beefy_wake_last_event_timestamp_seconds{event="campaign"} 1000.5',
        ):
            self.assertIn(line, text.splitlines())
        for m in ("phase", "campaigns_total", "power_cycles_total", "failures_total", "recoveries_total",
                  "last_event_timestamp_seconds"):
            self.assertIn(f"# HELP beefy_wake_{m} ", text)
            self.assertIn(f"# TYPE beefy_wake_{m} ", text)
        self.assertNotIn('event="recovery"', text)

    def test_textfile_never_raises(self):
        write_textfile("/nonexistent-dir/x.prom", self.SNAP)

if __name__ == "__main__":
    unittest.main()
