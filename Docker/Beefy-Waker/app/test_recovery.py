#!/usr/bin/env python3
"""Tests for the Beefy-Waker wake-recovery state machine (fake clock, plug, probe)."""
import unittest

from recovery import Recovery


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakePlug:
    def __init__(self):
        self.relay_state = True
        self.fail_set = False
        self.unreachable = False
        self.calls = []

    def relay(self):
        self.calls.append(("relay",))
        return None if self.unreachable else self.relay_state

    def set(self, on):
        self.calls.append(("set", on))
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
        self.rec = Recovery(
            probe=lambda port: port in self.up_from and self.clock.now >= self.up_from[port],
            send_wol=lambda: self.wols.append(self.clock.now),
            plug=self.plug,
            alert=lambda *a: self.alerts.append(a),
            write_metrics=self.snaps.append,
            clock=self.clock,
            wall=lambda: 1000.0 + self.clock.now,
        )

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
        self.run_to(40)
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
        self.run_to(200)
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

    def test_snapshot_counts(self):
        self.rec.start(22, False)
        self.rec.start(8096, True)
        snap = self.rec.snapshot()
        self.assertEqual(snap["campaigns"], {"0": 1, "1": 0})
        self.assertIn("campaign", snap["last"])


if __name__ == "__main__":
    unittest.main()
