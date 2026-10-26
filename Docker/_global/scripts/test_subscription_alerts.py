#!/usr/bin/env python3
"""Tests for subscription-alerts.py. Run: python3 test_subscription_alerts.py"""
import datetime as dt
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location("sa", Path(__file__).parent / "subscription-alerts.py")
sa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sa)

D = dt.date
TOML = """
[[subscriptions]]
name = "Treasure Maps"
kind = "indexer, free User API"
expires = 2026-11-18

[[subscriptions]]
name = "Eweka"
kind = "Usenet provider"
expires = 2026-11-18

[[subscriptions]]
name = "NZBgeek"
kind = "indexer"
lifetime = true
"""


def subs(*rows):
    return [{"name": n, "kind": "k", "expires": e} if e else {"name": n, "kind": "k", "lifetime": True} for n, e in rows]


def test_stage_boundaries():
    exp = D(2026, 12, 1)
    want = {31: None, 30: "yellow", 29: "yellow", 8: "yellow", 7: "orange", 1: "orange", 0: "red", -1: "expired", -2: None, -9: None}
    for left, stage in want.items():
        today = exp - dt.timedelta(days=left)
        assert sa.stage(left) == stage, left
        assert sa.stage((exp - today).days) == stage


def test_today_is_the_zurich_date():
    late = dt.datetime(2026, 10, 26, 23, 30, tzinfo=dt.timezone.utc)
    assert sa.zurich_today(late) == D(2026, 10, 27)
    summer = dt.datetime(2026, 7, 1, 21, 59, tzinfo=dt.timezone.utc)
    assert sa.zurich_today(summer) == D(2026, 7, 1)
    assert sa.zurich_today(summer + dt.timedelta(minutes=1)) == D(2026, 7, 2)


def test_lifetime_never_alerts():
    assert sa.pending(subs(("L", None)), D(2030, 1, 1), {}) == []


def test_far_future_none():
    assert sa.pending(subs(("A", D(2027, 6, 15))), D(2026, 10, 26), {}) == []


def test_first_run_with_23_days_sends_only_current_stage():
    out = sa.pending(subs(("A", D(2026, 11, 18))), D(2026, 10, 26), {})
    assert [(g["stage"], g["days"]) for g in out] == [("yellow", 23)]


def test_catch_up_deep_in_orange_sends_only_orange():
    out = sa.pending(subs(("A", D(2026, 11, 18))), D(2026, 11, 14), {})
    assert [g["stage"] for g in out] == ["orange"]


def test_once_per_stage_via_state():
    s = subs(("A", D(2026, 11, 18)))
    state = {}
    for g in sa.pending(s, D(2026, 10, 26), state):
        sa.mark(state, g)
    assert sa.pending(s, D(2026, 10, 27), state) == []
    assert [g["stage"] for g in sa.pending(s, D(2026, 11, 11), state)] == ["orange"]


def test_each_stage_fires_in_sequence():
    s = subs(("A", D(2026, 11, 18)))
    state, seen = {}, []
    day = D(2026, 10, 1)
    while day <= D(2026, 11, 25):
        for g in sa.pending(s, day, state):
            seen.append((str(day), g["stage"]))
            sa.mark(state, g)
        day += dt.timedelta(days=1)
    assert seen == [("2026-10-19", "yellow"), ("2026-11-11", "orange"), ("2026-11-18", "red"), ("2026-11-19", "expired")]


def test_renewal_resets_and_old_date_is_silent():
    state = {}
    old = subs(("A", D(2026, 11, 18)))
    for g in sa.pending(old, D(2026, 10, 26), state):
        sa.mark(state, g)
    new = subs(("A", D(2027, 11, 18)))
    assert sa.pending(new, D(2026, 11, 11), state) == []
    assert sa.pending(new, D(2026, 11, 18), state) == []
    out = sa.pending(new, D(2027, 10, 20), state)
    assert [g["stage"] for g in out] == ["yellow"]
    sa.prune(state, new)
    assert all("2026-11-18" not in k for k in state)


def test_renewal_after_orange_sent_new_date_starts_fresh_yellow():
    state = {}
    old = subs(("A", D(2026, 11, 18)))
    for g in sa.pending(old, D(2026, 11, 12), state):
        sa.mark(state, g)
    new = subs(("A", D(2026, 12, 10)))
    assert [g["stage"] for g in sa.pending(new, D(2026, 11, 12), state)] == ["yellow"]


def test_grouping_same_stage_same_date():
    s = subs(("A", D(2026, 11, 18)), ("B", D(2026, 11, 18)), ("C", D(2026, 11, 20)), ("D", D(2027, 1, 1)))
    out = sa.pending(s, D(2026, 10, 26), {})
    assert [(g["stage"], g["expires"], [x["name"] for x in g["items"]]) for g in out] == [
        ("yellow", D(2026, 11, 18), ["A", "B"]),
        ("yellow", D(2026, 11, 20), ["C"]),
    ]


def test_message_layout_single():
    g = sa.pending([{"name": "Treasure Maps", "kind": "indexer, free User API", "expires": D(2026, 11, 18)}], D(2026, 10, 19), {})[0]
    m = sa.render(g, cache_age_days=0)
    lines = m.split("\n")
    assert lines[0] == "🟡 <b>Treasure Maps ends in 30 days</b>"
    assert lines[1] == ""
    assert lines[2] == "📅 Wed, 18 Nov 2026"
    assert lines[3] == "• <b>Treasure Maps</b> · indexer, free User API"
    assert lines[4] == ""
    assert lines[5].startswith("<blockquote expandable>") and m.endswith("</blockquote>")
    assert "<code>indexer-bar/limits.toml</code>" in m and "`" not in m


def test_message_layout_group():
    g = sa.pending([{"name": "Treasure Maps", "kind": "indexer", "expires": D(2026, 11, 18)},
                    {"name": "Eweka", "kind": "Usenet provider", "expires": D(2026, 11, 18)}], D(2026, 10, 26), {})[0]
    lines = sa.render(g, 0).split("\n")
    assert lines[0] == "🟡 <b>2 subscriptions end in 23 days</b>"
    assert lines[2] == "📅 Wed, 18 Nov 2026"
    assert lines[3:5] == ["• <b>Treasure Maps</b> · indexer", "• <b>Eweka</b> · Usenet provider"]


def test_titles_per_stage_and_plural():
    mk = lambda today, *names: sa.pending(subs(*[(n, D(2026, 11, 18)) for n in names]), today, {})[0]
    assert sa.render(mk(D(2026, 11, 11), "A"), 0).split("\n")[0] == "🟠 <b>A ends in 7 days</b>"
    assert sa.render(mk(D(2026, 11, 17), "A"), 0).split("\n")[0] == "🟠 <b>A ends in 1 day</b>"
    assert sa.render(mk(D(2026, 11, 18), "A"), 0).split("\n")[0] == "🔴 <b>A ends today</b>"
    assert sa.render(mk(D(2026, 11, 19), "A"), 0).split("\n")[0] == "🔴 <b>A expired yesterday</b>"
    assert sa.render(mk(D(2026, 10, 19), "A", "B"), 0).split("\n")[0] == "🟡 <b>2 subscriptions end in 30 days</b>"
    assert sa.render(mk(D(2026, 11, 19), "A", "B"), 0).split("\n")[0] == "🔴 <b>2 subscriptions expired yesterday</b>"
    assert "📅 ended Wed, 18 Nov 2026" in sa.render(mk(D(2026, 11, 19), "A"), 0)


def test_html_is_escaped():
    g = sa.pending([{"name": "A<b>&Co", "kind": "x", "expires": D(2026, 11, 18)}], D(2026, 11, 18), {})[0]
    m = sa.render(g, 0)
    assert "A&lt;b&gt;&amp;Co" in m and "A<b>&Co" not in m


def test_cache_age_only_when_old():
    g = sa.pending(subs(("A", D(2026, 11, 18))), D(2026, 11, 18), {})[0]
    assert "list" not in sa.render(g, 0).lower().replace("limits.toml", "")
    assert "Subscription list is 3 days old" in sa.render(g, 3)
    assert "⚠️ Subscription list is 9 days old (beefy not reachable)" in sa.render(g, 9)


def test_stale_threshold():
    assert not sa.is_stale(7) and sa.is_stale(8)


def test_parse_subscriptions_rejects_garbage():
    assert [s["name"] for s in sa.parse_subscriptions(TOML)] == ["Treasure Maps", "Eweka", "NZBgeek"]
    for bad in ("not = [toml", "x = 1", '[[subscriptions]]\nname = "A"\n'):
        try:
            sa.parse_subscriptions(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_refresh_cache_keeps_old_copy_when_beefy_is_down():
    with tempfile.TemporaryDirectory() as d:
        cache = Path(d) / "limits.toml"
        cache.write_text(TOML)
        old = time.time() - 5 * 86400
        os.utime(cache, (old, old))
        assert sa.refresh_cache(cache, lambda: None) is False
        assert cache.read_text() == TOML
        assert abs(cache.stat().st_mtime - old) < 2
        assert abs(sa.cache_age_days(cache, time.time()) - 5) < 0.01


def test_refresh_cache_ignores_invalid_fetch():
    with tempfile.TemporaryDirectory() as d:
        cache = Path(d) / "limits.toml"
        cache.write_text(TOML)
        assert sa.refresh_cache(cache, lambda: "garbage = [") is False
        assert cache.read_text() == TOML


def test_refresh_cache_writes_new_copy():
    with tempfile.TemporaryDirectory() as d:
        cache = Path(d) / "limits.toml"
        assert sa.refresh_cache(cache, lambda: TOML) is True
        assert cache.read_text() == TOML
        assert sa.cache_age_days(cache, time.time()) < 0.01


def run(tmp, fetch, send, today, now=None):
    return sa.run(Path(tmp), fetch, send, today, now or time.time())


def test_run_sends_marks_and_does_not_repeat():
    sent = []
    with tempfile.TemporaryDirectory() as d:
        assert run(d, lambda: TOML, lambda m: sent.append(m) or True, D(2026, 10, 26)) == 0
        assert len(sent) == 1 and "Treasure Maps" in sent[0] and "Eweka" in sent[0] and "end in 23 days" in sent[0]
        run(d, lambda: TOML, lambda m: sent.append(m) or True, D(2026, 10, 27))
        assert len(sent) == 1
        assert json.loads((Path(d) / "state.json").read_text())


def test_run_failed_send_is_retried_next_time():
    sent = []
    with tempfile.TemporaryDirectory() as d:
        assert run(d, lambda: TOML, lambda m: False, D(2026, 10, 26)) == 1
        assert run(d, lambda: TOML, lambda m: sent.append(m) or True, D(2026, 10, 26)) == 0
        assert len(sent) == 1


def test_run_beefy_down_uses_cache_and_mentions_age():
    sent = []
    with tempfile.TemporaryDirectory() as d:
        run(d, lambda: TOML, lambda m: True, D(2026, 10, 1))
        cache = Path(d) / "limits.toml"
        old = time.time() - 9 * 86400
        os.utime(cache, (old, old))
        run(d, lambda: None, lambda m: sent.append(m) or True, D(2026, 11, 11))
        assert len(sent) == 1 and "end in 7 days" in sent[0] and "9 days old (beefy not reachable)" in sent[0]
        assert cache.read_text() == TOML


def test_run_without_any_cache_is_an_error_not_a_crash():
    with tempfile.TemporaryDirectory() as d:
        assert run(d, lambda: None, lambda m: True, D(2026, 10, 26)) == 1


def test_test_message():
    m = sa.test_message()
    assert m.split("\n")[0].startswith("🧪 <b>Test: ")


if __name__ == "__main__":
    import traceback
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    bad = 0
    for n, f in fns:
        try:
            f()
        except Exception:  # noqa: BLE001
            bad += 1
            print(f"FAIL {n}")
            traceback.print_exc()
    print(f"\n{len(fns) - bad}/{len(fns)} passed")
    sys.exit(1 if bad else 0)
