#!/usr/bin/env python3
"""Decision macros of config/custom_templates/plug_watch.jinja.   python3 tests/test_plug_watch.py

Rendered with Jinja's sandbox, which Home Assistant's template engine extends; the macros use only plain Jinja.
"""
import unittest
from pathlib import Path

from jinja2 import FileSystemLoader
from jinja2.sandbox import ImmutableSandboxedEnvironment

TEMPLATES = Path(__file__).resolve().parent.parent / "config" / "custom_templates"
ENV = ImmutableSandboxedEnvironment(loader=FileSystemLoader(TEMPLATES))


def call(macro: str, *args) -> str:
    src = "{% from 'plug_watch.jinja' import " + macro + " %}{{ " + macro + "(*args) }}"
    return ENV.from_string(src).render(args=args).strip()


class RelayVerdict(unittest.TestCase):
    def test_switch_without_command_alerts(self):
        self.assertEqual(call("relay_verdict", "on", "off", None), "alert")
        self.assertEqual(call("relay_verdict", "off", "on", None), "alert")

    def test_old_command_alerts(self):
        self.assertEqual(call("relay_verdict", "on", "off", 121), "alert")

    def test_recent_command_is_ordered(self):
        self.assertEqual(call("relay_verdict", "on", "off", 35), "ordered")
        self.assertEqual(call("relay_verdict", "off", "on", 120), "ordered")

    def test_unavailable_or_same_state_is_ignored(self):
        for frm, to in (("unavailable", "off"), ("on", "unavailable"), ("unknown", "on"), ("on", "on"), (None, "off")):
            self.assertEqual(call("relay_verdict", frm, to, None), "ignore", (frm, to))


class PowerDrop(unittest.TestCase):
    def test_running_to_zero_in_one_poll(self):
        self.assertEqual(call("power_drop", "31.0", "0.0"), "drop")
        self.assertEqual(call("power_drop", "15.1", "0.9"), "drop")

    def test_not_a_drop(self):
        for frm, to in (("15.0", "0.0"), ("31.0", "1.0"), ("31.0", "2.8"), ("unavailable", "0.0"), ("31.0", "unavailable"), ("2.8", "0.0")):
            self.assertEqual(call("power_drop", frm, to), "", (frm, to))


class PowerVerdict(unittest.TestCase):
    def test_relay_not_on_is_left_to_the_relay_alert(self):
        for relay in ("off", "unavailable", "unknown"):
            self.assertEqual(call("power_verdict", relay, None, "open"), "relay", relay)

    def test_recent_command_is_ordered(self):
        self.assertEqual(call("power_verdict", "on", 40, "open"), "ordered")

    def test_port_refused_before_power_off_is_clean(self):
        self.assertEqual(call("power_verdict", "on", None, "refused"), "clean")
        self.assertEqual(call("power_verdict", "on", 500, "refused"), "clean")

    def test_port_open_until_power_off_is_hard_off(self):
        self.assertEqual(call("power_verdict", "on", None, "open"), "hard_off")

    def test_no_port_history_is_unknown(self):
        for alive in ("unknown", "unavailable", None):
            self.assertEqual(call("power_verdict", "on", None, alive), "unknown", alive)


if __name__ == "__main__":
    unittest.main()
