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
GEN = "2026-10-01T03:00:00Z"


def item(id, title, kind, date, category="", lead=None, alert="telegram", **extra):
    lead = lead if lead is not None else ([5, 3, 1, 0] if kind == "ddns" else [30, 7, 0])
    return {"id": id, "title": title, "kind": kind, "category": category, "date": date, "lifetime": date is None and kind == "subscription",
            "source": "manual", "lead": lead, "alert": alert, "show": [], **extra}


SUBS = [item("tm", "Treasure Maps", "subscription", "2026-11-18", "indexer, free User API"),
        item("ew", "Eweka", "subscription", "2026-11-18", "Usenet provider"),
        item("geek", "NZBgeek", "subscription", None, "indexer")]
DOMAIN = item("dom", "holy-grail.ch", "domain", "2027-02-17", "domain, GoDaddy (DNS Cloudflare)", registrar="GoDaddy", renew="yearly at godaddy.com", dns="Cloudflare")
DDNS_ITEMS = [item("a", "a.ddns.net", "ddns", "2026-12-10", "No-IP hostname", confirmed="2026-11-10"),
              item("b", "b.ddns.net", "ddns", "2026-12-10", "No-IP hostname", confirmed="2026-11-10")]
OTHER = [item("cert", "TLS certificate x", "certificate", "2026-11-20", alert="prometheus"),
         item("film", "Film leaves the bin", "info", "2026-11-18", alert="none")]


def due_json(items, generated=GEN):
    return json.dumps({"version": 1, "generated": generated, "items": items})


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
    assert "<code>Due-Dates/due-dates.toml</code>" in m and "`" not in m


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
    assert "list is" not in sa.render(g, 0).lower()
    assert "Due-date list is 3 days old" in sa.render(g, 3)
    assert "⚠️ Due-date list is 9 days old (due-dates build failing)" in sa.render(g, 9)


def test_stale_threshold():
    assert not sa.is_stale(7) and sa.is_stale(8)


def test_parse_due_keeps_telegram_items_only():
    subs = sa.parse_due(due_json(SUBS + [DOMAIN] + DDNS_ITEMS + OTHER))
    assert [s["name"] for s in subs] == ["Treasure Maps", "Eweka", "NZBgeek", "holy-grail.ch", "a.ddns.net", "b.ddns.net"]
    assert subs[0] == {"name": "Treasure Maps", "kind": "indexer, free User API", "expires": D(2026, 11, 18), "lead": [30, 7, 0]}
    assert subs[2]["lifetime"] and "expires" not in subs[2]
    assert subs[4]["ddns"] and subs[4]["expires"] == D(2026, 12, 10)


def test_parse_due_rejects_garbage_and_empty_lists():
    for bad in ("not json", "[]", json.dumps({"items": []}), json.dumps({"items": [{"title": "x"}]})):
        try:
            sa.parse_due(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_item_without_date_is_skipped():
    assert sa.parse_due(due_json(SUBS[:1] + [item("d", "d.ch", "domain", None)])) == sa.parse_due(due_json(SUBS[:1]))


def test_stage_for_lead_lists():
    for left in range(-3, 40):
        assert sa.stage_for(left, [30, 7, 0]) == sa.stage(left), left
        assert sa.stage_for(left, [5, 3, 1, 0], ddns=True) == sa.stage(left, True), left
    want = {8: None, 7: "yellow", 1: "yellow", 0: "red", -1: "expired", -2: None}
    for left, st in want.items():
        assert sa.stage_for(left, [7, 0]) == st, left


def test_reminder_sequence_with_its_own_lead():
    s = [{"name": "Backup decision", "kind": "", "expires": D(2026, 12, 22), "lead": [7, 0], "reminder": True, "howto": "Delete it."}]
    state, seen = {}, []
    day = D(2026, 12, 1)
    while day <= D(2026, 12, 25):
        for g in sa.pending(s, day, state):
            seen.append((day, g["stage"], sa.render(g, 0).split("\n")[0]))
            sa.mark(state, g)
        day += dt.timedelta(days=1)
    assert seen == [(D(2026, 12, 15), "yellow", "🟡 <b>Backup decision due in 7 days</b>"),
                    (D(2026, 12, 22), "red", "🔴 <b>Backup decision due today</b>"),
                    (D(2026, 12, 23), "expired", "🔴 <b>Backup decision was due yesterday</b>")]


def test_token_howto_and_the_date_hint():
    s = sa.parse_due(due_json([item("hub", "Docker Hub token", "token", "2027-11-15", "WG Chores image builds", howto="New token on hub.docker.com.")]))
    m = sa.render(sa.pending(s, D(2027, 10, 16), {})[0], 0)
    assert "🟡 <b>Docker Hub token ends in 30 days</b>" in m
    assert "New token on hub.docker.com. Then set the new date (<code>date</code>) in <code>Due-Dates/due-dates.toml</code> (fastpi)." in m


def json_age_days(generated, now):
    return sa.list_age_days(due_json(SUBS, generated), now)


def test_list_age_from_generated():
    now = dt.datetime(2026, 10, 10, 3, 0, tzinfo=dt.timezone.utc).timestamp()
    assert abs(json_age_days("2026-10-01T03:00:00Z", now) - 9) < 0.01


def write_due(d, items, generated=None):
    p = Path(d) / "due-dates.json"
    p.write_text(due_json(items, generated or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    return p


def run(tmp, items, send, today, now=None, note=None):
    return sa.run(Path(tmp) / "state", write_due(tmp, items), send, today, now or time.time(), note=note or (lambda t: True))


def test_yellow_goes_to_the_digest_not_telegram_and_does_not_repeat():
    sent, noted = [], []
    with tempfile.TemporaryDirectory() as d:
        assert run(d, SUBS, lambda m: sent.append(m) or True, D(2026, 10, 26), note=lambda t: noted.append(t) or True) == 0
        assert sent == []
        assert noted == ["2 subscriptions end in 23 days (Wed, 18 Nov 2026): Treasure Maps, Eweka"]
        run(d, SUBS, lambda m: sent.append(m) or True, D(2026, 10, 27), note=lambda t: noted.append(t) or True)
        assert len(noted) == 1 and sent == []
        assert json.loads((Path(d) / "state" / "state.json").read_text())


def test_orange_still_goes_to_telegram_once():
    sent, noted = [], []
    with tempfile.TemporaryDirectory() as d:
        assert run(d, SUBS, lambda m: sent.append(m) or True, D(2026, 11, 11), note=lambda t: noted.append(t) or True) == 0
        assert noted == [] and len(sent) == 1 and "end in 7 days" in sent[0]
        run(d, SUBS, lambda m: sent.append(m) or True, D(2026, 11, 12), note=lambda t: noted.append(t) or True)
        assert len(sent) == 1


def test_digest_note_is_plain_text():
    noted = []
    with tempfile.TemporaryDirectory() as d:
        run(d, [item("x", "A & <B>", "subscription", "2026-11-18")], lambda m: True, D(2026, 10, 26), note=lambda t: noted.append(t) or True)
    assert noted == ["A & <B> ends in 23 days (Wed, 18 Nov 2026)"]


def test_notify_digest_calls_the_shared_helper():
    calls = []
    orig = sa.subprocess.run
    sa.subprocess.run = lambda args, **kw: calls.append(args) or type("R", (), {"returncode": 0})()
    try:
        assert sa.notify_digest("x ends in 3 days")
    finally:
        sa.subprocess.run = orig
    assert calls == [[str(sa.NOTIFY), "digest", "subscription-alerts", "x ends in 3 days"]]


def test_run_failed_send_is_retried_next_time():
    sent = []
    with tempfile.TemporaryDirectory() as d:
        assert run(d, SUBS, lambda m: False, D(2026, 11, 11)) == 1
        assert run(d, SUBS, lambda m: sent.append(m) or True, D(2026, 11, 11)) == 0
        assert len(sent) == 1


def test_run_failed_note_is_retried_next_time():
    noted = []
    with tempfile.TemporaryDirectory() as d:
        assert run(d, SUBS, lambda m: True, D(2026, 10, 26), note=lambda t: False) == 1
        assert run(d, SUBS, lambda m: True, D(2026, 10, 26), note=lambda t: noted.append(t) or True) == 0
        assert len(noted) == 1


def test_run_old_list_still_alerts_and_mentions_age():
    sent = []
    with tempfile.TemporaryDirectory() as d:
        p = write_due(d, SUBS, "2026-11-02T03:00:00Z")
        now = dt.datetime(2026, 11, 11, 4, 0, tzinfo=dt.timezone.utc).timestamp()
        assert sa.run(Path(d) / "state", p, lambda m: sent.append(m) or True, D(2026, 11, 11), now) == 0
        assert len(sent) == 1 and "end in 7 days" in sent[0] and "9 days old (due-dates build failing)" in sent[0]


def test_run_without_the_list_is_an_error_not_a_crash():
    with tempfile.TemporaryDirectory() as d:
        assert sa.run(Path(d) / "state", Path(d) / "missing.json", lambda m: True, D(2026, 10, 26), time.time()) == 1


def test_domain_howto():
    s = sa.parse_due(due_json([DOMAIN]))
    assert s[0]["howto"] == "Renew holy-grail.ch at GoDaddy (yearly at godaddy.com); Cloudflare only does the DNS. Then set the new date (<code>date</code>) in <code>Due-Dates/due-dates.toml</code> (fastpi)."


def test_run_warns_for_a_domain_with_its_own_howto():
    sent = []
    with tempfile.TemporaryDirectory() as d:
        assert run(d, SUBS + [DOMAIN], lambda m: sent.append(m) or True, D(2027, 2, 10)) == 0
        assert len(sent) == 1 and "holy-grail.ch ends in 7 days" in sent[0] and "· domain, GoDaddy (DNS Cloudflare)" in sent[0]
        assert "Renew holy-grail.ch at GoDaddy (yearly at godaddy.com)" in sent[0]


def ddns_subs():
    return sa.parse_due(due_json(DDNS_ITEMS))


def test_ddns_items_are_flagged():
    got = ddns_subs()
    assert [(s["name"], s["expires"], s["kind"]) for s in got] == [("a.ddns.net", D(2026, 12, 10), "No-IP hostname"), ("b.ddns.net", D(2026, 12, 10), "No-IP hostname")]
    assert all(s["ddns"] for s in got)


def test_ddns_stage_timing():
    want = {8: None, 6: None, 5: "yellow", 4: "yellow", 3: "orange", 2: "orange", 1: "red1", 0: "red", -1: "expired", -2: None}
    for left, st in want.items():
        assert sa.stage(left, True) == st, left


def test_ddns_sequence_once_each_and_fresh_on_new_date():
    state = {}
    seen = []
    for day in range(0, 33):
        today = D(2026, 11, 10) + dt.timedelta(days=day)
        for g in sa.pending(ddns_subs(), today, state):
            seen.append((today, g["stage"], len(g["items"])))
            sa.mark(state, g)
    assert seen == [(D(2026, 12, 5), "yellow", 2), (D(2026, 12, 7), "orange", 2), (D(2026, 12, 9), "red1", 2), (D(2026, 12, 10), "red", 2), (D(2026, 12, 11), "expired", 2)]
    new = [dict(s, expires=D(2027, 1, 9)) for s in ddns_subs()]
    assert sa.pending(new, D(2027, 1, 4), state)[0]["stage"] == "yellow"


def test_ddns_message_layout():
    g = sa.pending(ddns_subs(), D(2026, 12, 5), {})[0]
    m = sa.render(g, 0)
    lines = m.split("\n")
    assert lines[0] == "🟡 <b>No-IP confirm due in 5 days</b>"
    assert lines[2] == "📅 Thu, 10 Dec 2026"
    assert "• <b>a.ddns.net</b> · No-IP hostname" in m and "• <b>b.ddns.net</b> · No-IP hostname" in m
    assert "noip.com" in m and "Dynamic DNS" in m and "No-IP confirmed" in m and "confirmed = " in m and "Due-Dates/due-dates.toml" in m
    assert sa.render(sa.pending(ddns_subs(), D(2026, 12, 10), {})[0], 0).split("\n")[0] == "🔴 <b>No-IP confirm last day</b>"
    assert sa.render(sa.pending(ddns_subs(), D(2026, 12, 11), {})[0], 0).split("\n")[0] == "🔴 <b>No-IP confirm deadline passed</b>"
    one = sa.pending(ddns_subs()[:1], D(2026, 12, 9), {})[0]
    assert sa.render(one, 0).split("\n")[0] == "🔴 <b>No-IP confirm due in 1 day</b>"
    assert "deletes the hostname today" in sa.render(sa.pending(ddns_subs(), D(2026, 12, 10), {})[0], 0)
    assert "re-create the hostname at No-IP" in sa.render(sa.pending(ddns_subs(), D(2026, 12, 11), {})[0], 0)


def test_run_sends_ddns_once():
    sent = []
    with tempfile.TemporaryDirectory() as d:
        assert run(d, SUBS + DDNS_ITEMS, lambda m: sent.append(m) or True, D(2026, 12, 7)) == 0
        assert len([m for m in sent if "No-IP" in m]) == 1
        assert run(d, SUBS + DDNS_ITEMS, lambda m: sent.append(m) or True, D(2026, 12, 8)) == 0
        assert len([m for m in sent if "No-IP" in m]) == 1


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
