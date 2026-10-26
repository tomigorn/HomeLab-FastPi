#!/usr/bin/env python3
"""Tests for mam-points.py. Run: python3 test_mam_points.py"""
import datetime as dt
import importlib.util
import json
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location("mp", Path(__file__).parent / "mam-points.py")
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 10, 26, 14, 15, tzinfo=UTC)


def h(n):
    return T0 + dt.timedelta(hours=n)


def st(points=51655, rate=309.9, epoch=1):
    return {"points": points, "rate": rate, "updated": T0.isoformat(), "epoch": epoch, "alerted": []}


def raises(fn, *a):
    try:
        fn(*a)
    except ValueError:
        return True
    return False


def test_estimate_math():
    assert mp.estimate(st(), T0) == 51655
    assert abs(mp.estimate(st(), h(10)) - (51655 + 3099)) < 1e-6


def test_estimate_clamped_at_cap():
    assert mp.estimate(st(), h(100000)) == mp.CAP == 99999


def test_estimate_never_before_timestamp():
    assert mp.estimate(st(), h(-5)) == 51655


def test_crossing_time():
    t = mp.crossing(st(), 90000)
    assert abs((t - T0).total_seconds() / 3600 - (90000 - 51655) / 309.9) < 1e-6
    assert mp.crossing(st(points=95000), 90000) < T0


def test_set_new_epoch():
    s = mp.cmd_set(st(epoch=3), 1000, h(1))
    assert (s["points"], s["epoch"], s["alerted"]) == (1000, 4, [])
    assert s["rate"] == 309.9 and s["updated"] == h(1).isoformat()


def test_set_needs_rate_when_no_state():
    assert raises(mp.cmd_set, None, 10, T0)
    s = mp.cmd_set(None, 10, T0, rate=5)
    assert s["rate"] == 5 and s["epoch"] == 1


def test_reset_is_set_zero():
    s = mp.cmd_reset(st(), h(1))
    assert s["points"] == 0 and s["epoch"] == 2


def test_spent_subtracts_estimate():
    s = mp.cmd_spent(st(), 25000, h(10))
    assert abs(s["points"] - (51655 + 3099 - 25000)) < 1e-6
    assert s["updated"] == h(10).isoformat() and s["epoch"] == 2 and s["alerted"] == []


def test_spent_from_capped_estimate():
    s = mp.cmd_spent(st(), 10000, h(100000))
    assert s["points"] == 89999


def test_rate_rebaselines():
    s = mp.cmd_rate(st(), 100, h(10))
    assert abs(s["points"] - (51655 + 3099)) < 1e-6 and s["rate"] == 100 and s["epoch"] == 2


def test_validation():
    assert raises(mp.cmd_set, st(), -1, T0)
    assert raises(mp.cmd_set, st(), 100000, T0)
    assert raises(mp.cmd_set, st(), float("nan"), T0)
    assert raises(mp.cmd_spent, st(), 0, T0)
    assert raises(mp.cmd_spent, st(), -5, T0)
    assert raises(mp.cmd_spent, st(), 60000, T0)
    assert raises(mp.cmd_rate, st(), 0, T0)
    assert raises(mp.cmd_rate, st(), -2, T0)
    assert raises(mp.cmd_rate, st(), float("inf"), T0)
    assert raises(mp.cmd_rate, None, 5, T0)
    assert mp.parse_number("51,655") == 51655 and raises(mp.parse_number, "abc")


def test_due_stages_once_per_epoch():
    s = st(points=89000)
    assert mp.due(s, T0) == []
    assert mp.due(s, h(4)) == ["yellow"]
    s["alerted"] = ["yellow"]
    assert mp.due(s, h(4)) == []
    assert mp.due(s, h(40)) == ["red"]
    s["alerted"] = ["yellow", "red"]
    assert mp.due(s, h(400)) == []


def test_both_crossed_in_one_night_sends_only_red():
    s = st(points=89000)
    assert mp.due(s, h(100)) == ["red"]


def test_check_sends_and_marks():
    sent = []
    s = st(points=89000)
    s2 = mp.check(s, h(4), lambda m: sent.append(m) or True)
    assert len(sent) == 1 and s2["alerted"] == ["yellow"]
    s3 = mp.check(s2, h(5), lambda m: sent.append(m) or True)
    assert len(sent) == 1 and s3["alerted"] == ["yellow"]


def test_failed_send_retried():
    s = st(points=89000)
    s2 = mp.check(s, h(4), lambda m: False)
    assert s2["alerted"] == []


def test_new_epoch_realerts():
    sent = []
    s = mp.check(st(points=89000), h(4), lambda m: sent.append(m) or True)
    s = mp.cmd_set(s, 89000, h(5))
    mp.check(s, h(9), lambda m: sent.append(m) or True)
    assert len(sent) == 2


def test_yellow_message_layout():
    m = mp.render("yellow", st(points=89000), h(4), preview=True)
    lines = m.split("\n")
    assert lines[0].startswith("🧪 Preview: 🟡 <b>") and lines[0].endswith("</b>")
    assert lines[1] == "" and lines[2].startswith("📅")
    assert any(l.startswith("• ") for l in lines)
    assert "99,999" in m and "day" in m and "<blockquote expandable>" in m
    assert "309.9" in m and "mam-points set" in m and "mam-points spent" in m


def test_red_message():
    m = mp.render("red", st(points=95000), h(40))
    assert m.startswith("🔴 <b>") and "wasted" in m and "Preview" not in m


def test_zurich_dates_dst_safe():
    before = dt.datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    assert mp.fmt_when(before).endswith("02:30")
    after = dt.datetime(2026, 10, 25, 2, 30, tzinfo=UTC)
    assert mp.fmt_when(after).endswith("03:30")
    assert mp.fmt_when(dt.datetime(2026, 7, 1, 22, 30, tzinfo=UTC)).startswith("Thu, 2 Jul 2026")


def test_status_text():
    t = mp.status_text(st(), T0)
    assert "51,655" in t and "309.9" in t and "90,000" in t and "99,999" in t


def test_state_roundtrip_and_prom():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "state.json"
        assert mp.load(p) is None
        mp.save(p, st())
        assert mp.load(p)["points"] == 51655
        prom = Path(d) / "mam_points.prom"
        mp.write_prom(prom, st(), h(10))
        txt = prom.read_text()
        assert "mam_points_estimated 54754" in txt and "mam_points_rate_per_hour 309.9" in txt
        assert "mam_points_last_update_timestamp_seconds" in txt


if __name__ == "__main__":
    fails = 0
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    for name, fn in tests:
        try:
            fn()
            print("ok  ", name)
        except Exception as e:
            fails += 1
            print("FAIL", name, repr(e))
    print(f"{len(tests) - fails}/{len(tests)} passed")
    raise SystemExit(1 if fails else 0)
