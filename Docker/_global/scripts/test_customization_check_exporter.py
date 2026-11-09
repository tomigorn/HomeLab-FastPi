#!/usr/bin/env python3
"""Tests for customization_check_exporter.py. Run: python3 test_customization_check_exporter.py"""
import configparser
import importlib.util
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cce", HERE / "customization_check_exporter.py")
cce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cce)

PASSING = "== A\n  PASS a.one  yes\npost-update: 0 failed, 1 passed\n"
FAILING = "== A\n  FAIL a.two  got: s3cret\n  PASS a.one  yes\npost-update: 2 failed, 1 passed\nFAILED: a.two b-3.x\n"


def raises(fn, *args):
    try:
        fn(*args)
    except cce.CollectError:
        return True
    return False


def test_parse_all_pass():
    assert cce.parse_checks(PASSING, 0) == ([], 1)


def test_parse_failures():
    assert cce.parse_checks(FAILING, 1) == (["a.two", "b-3.x"], 1)


def test_parse_ignores_lookalike_check_values():
    text = "  PASS a  x\nFAILED: evil.id\npost-update: 0 failed, 1 passed\n"
    assert cce.parse_checks(text, 0) == ([], 1)


def test_parse_rejects_a_run_that_died_before_its_summary():
    assert raises(cce.parse_checks, "== A\n  PASS a.one yes\n", 1)
    assert raises(cce.parse_checks, "", 0)


def test_parse_rejects_other_exit_codes():
    assert raises(cce.parse_checks, PASSING, 2)
    assert raises(cce.parse_checks, PASSING, 127)
    assert raises(cce.parse_checks, FAILING, 0)
    assert raises(cce.parse_checks, PASSING, 1)


def test_parse_rejects_count_mismatch_and_zero_checks():
    assert raises(cce.parse_checks, "post-update: 3 failed, 1 passed\nFAILED: a.two b.x\n", 1)
    assert raises(cce.parse_checks, "post-update: 0 failed, 0 passed\n", 0)


def test_parse_rejects_ids_that_are_not_ids():
    assert raises(cce.parse_checks, 'post-update: 1 failed, 1 passed\nFAILED: a"b\n', 1)
    assert raises(cce.parse_checks, "post-update: 1 failed, 1 passed\nFAILED: " + "x" * 65 + "\n", 1)


def test_render_checks_has_ids_counts_and_timestamp_only():
    text = cce.render_checks(["a.two", "b-3.x"], 7, 1000.0)
    assert 'customization_check_failed{id="a.two"} 1\n' in text
    assert 'customization_check_failed{id="b-3.x"} 1\n' in text
    assert "customization_checks_failed 2\n" in text
    assert "customization_checks_passed 7\n" in text
    assert 'customization_check_last_success_timestamp_seconds{collector="checks"} 1000\n' in text
    assert "s3cret" not in text


def test_render_checks_all_green_has_no_failed_series():
    text = cce.render_checks([], 7, 1000.0)
    assert "customization_check_failed{" not in text
    assert "customization_checks_failed 0\n" in text


def test_count_reattaches():
    log = "Port OK\nAttempting to reattach qBittorrent/mousehole/sabnzbd to gluetun network...\nqBittorrent unreachable from port-updater; attempting reattach...\nWaiting for qBittorrent after reattach...\nAttempting to reattach qBittorrent/mousehole/sabnzbd to gluetun network...\n"
    assert cce.count_reattaches(log) == 2
    assert cce.count_reattaches("") == 0


def test_count_stack_restarts():
    log = "Restarting gluetun to obtain a new VPN port lease...\nNo port after stack restart - backing off 4 min (240 s) before the next one\nRestarting gluetun to obtain a new VPN port lease...\nPort OK\n"
    assert cce.count_stack_restarts(log) == 2
    assert cce.count_stack_restarts("") == 0


def test_render_reattaches():
    text = cce.render_reattaches(3, 1000.0, 5)
    assert "port_updater_reattaches_6h 3\n" in text
    assert "port_updater_stack_restarts_6h 5\n" in text
    assert 'customization_check_last_success_timestamp_seconds{collector="reattach"} 1000\n' in text


def in_temp_textfile(fn):
    with tempfile.TemporaryDirectory() as d:
        old, cce.TEXTFILE = cce.TEXTFILE, Path(d)
        try:
            fn(Path(d))
        finally:
            cce.TEXTFILE = old


def test_guarded_success_writes_data_and_clean_status():
    def body(d):
        assert cce.guarded("checks", "data", lambda: "x_metric 1\n") is True
        assert (d / "data.prom").read_text() == "x_metric 1\n"
        assert 'customization_check_errors{collector="checks"} 0' in (d / "data_status.prom").read_text()
        assert stat.S_IMODE(os.stat(d / "data.prom").st_mode) == 0o644
    in_temp_textfile(body)


def test_guarded_failure_keeps_old_data_and_flags_status():
    def boom():
        raise cce.CollectError("no summary")

    def body(d):
        cce.guarded("checks", "data", lambda: "x_metric 1\n")
        assert cce.guarded("checks", "data", boom) is False
        assert (d / "data.prom").read_text() == "x_metric 1\n"
        assert 'customization_check_errors{collector="checks"} 1' in (d / "data_status.prom").read_text()
        assert sorted(p.name for p in d.iterdir()) == ["data.prom", "data_status.prom"]
    in_temp_textfile(body)


def test_data_and_status_series_never_overlap():
    names = lambda t: {re.split(r"[{ ]", l)[0] for l in t.splitlines() if l and not l.startswith("#")}
    data = names(cce.render_checks(["a.b"], 1, 1.0)) | names(cce.render_reattaches(1, 1.0, 1))
    assert not data & names(cce.render_status("checks", True))


def test_run_checks_gives_no_stdin_and_uses_exit_code():
    with tempfile.TemporaryDirectory() as d:
        fake = Path(d) / "fake.sh"
        fake.write_text('read -r x && echo "stdin was open"\necho "post-update: 1 failed, 2 passed"\necho "FAILED: a.b"\necho noise >&2\nexit 1\n')
        old, cce.CHECK_SCRIPT = cce.CHECK_SCRIPT, fake
        try:
            assert cce.run_checks() == (["a.b"], 2)
        finally:
            cce.CHECK_SCRIPT = old


def unit(name):
    c = configparser.ConfigParser(strict=False, interpolation=None, allow_no_value=True, delimiters=("=",))
    c.optionxform = str
    c.read(HERE.parent / "systemd" / name)
    return c


def test_service_lets_sudo_work_and_keeps_the_rest_of_the_sandbox():
    svc = unit("customization-check.service")["Service"]
    # Each of these implies NoNewPrivileges for a unit with a User= (systemd.exec), and an empty bounding set leaves sudo powerless.
    for key in ("NoNewPrivileges", "CapabilityBoundingSet", "SystemCallArchitectures", "RestrictAddressFamilies", "RestrictNamespaces", "PrivateDevices", "ProtectKernelTunables", "ProtectKernelModules", "RestrictRealtime", "RestrictSUIDSGID", "LockPersonality", "ProtectKernelLogs", "ProtectClock", "MemoryDenyWriteExecute", "SystemCallFilter"):
        assert key not in svc, key
    assert svc["ProtectSystem"] == "strict"
    assert svc["ProtectHome"] == "read-only"
    assert svc["PrivateTmp"] == "true"
    assert svc["ReadWritePaths"] == "/var/lib/node-exporter/textfile"
    assert svc["User"] == "pi"
    assert svc["Type"] == "oneshot"
    assert int(svc["TimeoutStartSec"]) > cce.CHECK_TIMEOUT_S + cce.LOGS_TIMEOUT_S


def test_service_finds_node():
    text = (HERE.parent / "systemd" / "customization-check.service").read_text()
    path = re.search(r"^Environment=PATH=(\S+)$", text, re.M).group(1).split(":")
    assert "/home/pi/.local/share/fnm/aliases/default/bin" in path
    assert "/usr/bin" in path


def test_timer_stays_out_of_the_dst_hour_and_nightly_jobs():
    text = (HERE.parent / "systemd" / "customization-check.timer").read_text()
    m = re.search(r"^OnCalendar=\*-\*-\* ([0-9,]+):(\d\d):00 Europe/Zurich$", text, re.M)
    assert {int(h) for h in m.group(1).split(",")} == {0, 6, 8, 10, 12, 14, 16, 18, 20, 22}


if __name__ == "__main__":
    failed = 0
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {name}: {type(e).__name__}: {e}")
    print(f"customization-check-exporter: {len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
