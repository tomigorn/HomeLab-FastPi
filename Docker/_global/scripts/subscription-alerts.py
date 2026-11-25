#!/usr/bin/env python3
"""Telegram warnings for every date in Due-Dates (due-dates.json, built from Docker/Due-Dates/due-dates.toml) with alert = telegram. See README "subscription-alerts".
Stages per date from its lead days: default [30, 7, 0] = yellow <= 30 days left, orange <= 7, red on the date, red "expired yesterday" the day after. Each stage once per (item, date); a new date starts fresh.
Yellow is no Telegram message: a note in the 19:00 daily digest (notify.sh digest); orange and later go to Telegram.
DDNS hostnames (lead [5, 3, 1, 0]): yellow 5-4 days left, orange 3-2, red 1 day left, red on the end date (morning), red "deadline passed" the day after. Reminders say "due" instead of "ends".
Usage: subscription-alerts.py [--test]"""
import datetime as dt
import html
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Zurich")
HERE = Path(__file__).resolve().parent
OOB = HERE / "oob-alert.sh"
NOTIFY = HERE / "notify.sh"
STATE_DIR = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/subscription-alerts"))
DUE_JSON = Path(os.environ.get("DUE_DATES_JSON", "/var/lib/due-dates/due-dates.json"))
STALE_DAYS = 7
EMOJI = {"yellow": "🟡", "orange": "🟠", "red": "🔴", "expired": "🔴", "red1": "🔴"}
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
SOURCE = "<code>Due-Dates/due-dates.toml</code> (fastpi)"
DDNS_HOWTO = ("Confirm at noip.com: log in, Dynamic DNS, confirm the hostname (or click the link in No-IP's mail).\n"
              f"Then tell Claude \"No-IP confirmed\" or set <code>confirmed = &lt;date&gt;</code> in {SOURCE}.")
DATE_HINT = f"set the new date (<code>date</code>) in {SOURCE}."
HOWTO = f"After renewing: {DATE_HINT} The bars and these warnings follow within 10 minutes."
LEAD = [30, 7, 0]
DDNS_LEAD = [5, 3, 1, 0]


def zurich_today(now):
    return now.astimezone(TZ).date()


def stage_for(left, lead, ddns=False):
    """Stage for days left: the last lead day 0 is red, the ones before it yellow, orange, then (ddns) red1; the day after the date is expired."""
    if left == -1:
        return "expired"
    lead = sorted(lead, reverse=True)
    names = ["yellow", "orange", "red1"] if ddns else ["yellow", "orange", "orange"]
    hit = None
    for i, d in enumerate(lead):
        if left <= d:
            hit = "red" if d == 0 else names[min(i, len(names) - 1)]
    return hit if left >= 0 else None


def stage(left, ddns=False):
    return stage_for(left, DDNS_LEAD if ddns else LEAD, ddns)


def domain_howto(i):
    d = i["title"]
    where = f"Renew {d} at {i['registrar']}" + (f" ({i['renew']})" if i.get("renew") else "") if i.get("registrar") else f"Renew {d} at its registrar"
    dns = f"; {i['dns']} only does the DNS" if i.get("dns") else ""
    return f"{where}{dns}. Then {DATE_HINT}"


def parse_due(text):
    """due-dates.json -> the items that alert by Telegram, as {name, kind, expires | lifetime, lead, ...}."""
    try:
        items = json.loads(text)["items"]
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(f"not a due-dates list: {e}") from e
    if not isinstance(items, list) or not items:
        raise ValueError("empty due-dates list")
    subs = []
    for i in items:
        if not isinstance(i, dict) or "title" not in i or "alert" not in i:
            raise ValueError(f"item {i!r}: needs title and alert")
        if i["alert"] != "telegram" or not (i.get("lifetime") or i.get("date")):
            continue
        s = {"name": i["title"], "kind": i.get("category", "")}
        if i.get("lifetime"):
            s["lifetime"] = True
            subs.append(s)
            continue
        s["expires"] = dt.date.fromisoformat(i["date"])
        s["lead"] = i.get("lead") or LEAD
        if i.get("kind") == "ddns":
            s.update(ddns=True, howto=DDNS_HOWTO)
        elif i.get("kind") == "domain":
            s["howto"] = domain_howto(i)
        elif i.get("howto"):
            s["howto"] = f"{i['howto']} Then {DATE_HINT}"
        if i.get("kind") == "reminder":
            s["reminder"] = True
        subs.append(s)
    return subs


def key(s):
    return f"{s['name']}|{s['expires'].isoformat()}"


def pending(subs, today, state):
    groups = {}
    for s in subs:
        if s.get("lifetime"):
            continue
        left = (s["expires"] - today).days
        st = stage_for(left, s.get("lead") or (DDNS_LEAD if s.get("ddns") else LEAD), s.get("ddns", False))
        if st is None or st in state.get(key(s), []):
            continue
        g = groups.setdefault((st, s["expires"], bool(s.get("ddns"))), {"stage": st, "expires": s["expires"], "days": left, "items": []})
        g["items"].append(s)
    return sorted(groups.values(), key=lambda g: (g["expires"], g["stage"]))


def mark(state, group):
    for s in group["items"]:
        state.setdefault(key(s), []).append(group["stage"])


def prune(state, subs):
    live = {key(s) for s in subs if not s.get("lifetime")}
    for k in [k for k in state if k not in live]:
        del state[k]


def is_stale(age_days):
    return age_days > STALE_DAYS


def ddns_howto(st):
    if st == "red":
        return "Last day: confirm now or No-IP deletes the hostname today.\n" + DDNS_HOWTO
    if st == "expired":
        return f"Deadline passed: re-create the hostname at No-IP (noip.com, Dynamic DNS), point it at the WAN address.\nThen set <code>confirmed = &lt;date&gt;</code> in {SOURCE}."
    return DDNS_HOWTO


def headline(group):
    """Plain-text subject and "ends in N days" part of the title."""
    items, st, d = group["items"], group["stage"], group["days"]
    n = len(items)
    subject = items[0]["name"] if n == 1 else f"{n} subscriptions"
    if all(s.get("ddns") for s in items):
        subject = "No-IP confirm"
        when = {"expired": "deadline passed", "red": "last day"}.get(st, f"due in {d} day{'' if d == 1 else 's'}")
    elif all(s.get("reminder") for s in items):
        when = {"expired": "was due yesterday", "red": "due today"}.get(st, f"due in {d} day{'' if d == 1 else 's'}")
    elif st == "expired":
        when = "expired yesterday"
    elif st == "red":
        when = "ends today" if n == 1 else "end today"
    else:
        when = f"{'ends' if n == 1 else 'end'} in {d} day{'' if d == 1 else 's'}"
    return subject, when


def day_text(e):
    return f"{WEEKDAYS[e.weekday()]}, {e.day} {MONTHS[e.month - 1]} {e.year}"


def digest_text(group):
    subject, when = headline(group)
    names = f": {', '.join(s['name'] for s in group['items'])}" if len(group["items"]) > 1 else ""
    return f"{subject} {when} ({day_text(group['expires'])}){names}"


def render(group, cache_age_days):
    items, st = group["items"], group["stage"]
    subject, when = headline(group)
    e = group["expires"]
    lines = [f"{EMOJI[st]} <b>{html.escape(subject)} {when}</b>", "",
             f"📅 {'deadline was ' if st == 'expired' and all(s.get('ddns') for s in items) else 'ended ' if st == 'expired' else ''}{day_text(e)}"]
    for s in items:
        kind = f" · {html.escape(s['kind'])}" if s.get("kind") else ""
        lines.append(f"• <b>{html.escape(s['name'])}</b>{kind}")
    age = int(cache_age_days)
    if is_stale(cache_age_days):
        lines.append(f"⚠️ Due-date list is {age} days old (due-dates build failing)")
    howto = "\n".join(([HOWTO] if any("howto" not in s for s in items) else []) + [ddns_howto(st) if s.get("ddns") else s["howto"] for s in items if "howto" in s])
    details = howto + (f"\nDue-date list is {age} day{'' if age == 1 else 's'} old." if 1 <= age and not is_stale(cache_age_days) else "")
    lines += ["", f"<blockquote expandable>{details}</blockquote>"]
    return "\n".join(lines)


def test_message():
    return "🧪 <b>Test: Example Service ends in 30 days</b>\n\n📅 Wed, 18 Nov 2026\n• <b>Example Service</b> · indexer\n\n<blockquote expandable>Test of the subscription alert path (sent by hand, not a real deadline).</blockquote>"


def list_age_days(text, now):
    gen = dt.datetime.fromisoformat(json.loads(text)["generated"].replace("Z", "+00:00"))
    return (now - gen.timestamp()) / 86400


def send_oob(msg):
    return subprocess.run([str(OOB), msg]).returncode == 0


def notify_digest(text):
    return subprocess.run([str(NOTIFY), "digest", "subscription-alerts", text]).returncode == 0


def run(state_dir, due_json, send, today, now, note=notify_digest):
    state_file = state_dir / "state.json"
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        text = Path(due_json).read_text()
        subs, age = parse_due(text), list_age_days(text, now)
    except (OSError, ValueError, KeyError) as e:
        print(f"subscription-alerts: {due_json} unusable: {e}", file=sys.stderr)
        return 1
    if is_stale(age):
        print(f"subscription-alerts: due-date list is {int(age)} days old (due-dates build failing)", file=sys.stderr)
    try:
        state = json.loads(state_file.read_text())
    except (OSError, ValueError):
        state = {}
    failed = 0
    for g in pending(subs, today, state):
        digest = g["stage"] == "yellow"
        if note(digest_text(g)) if digest else send(render(g, age)):
            mark(state, g)
            print(f"subscription-alerts: {'digest note' if digest else 'sent'} {g['stage']} for {', '.join(s['name'] for s in g['items'])} ({g['expires']})")
        else:
            failed += 1
            print(f"subscription-alerts: send failed for {g['stage']} {g['expires']}", file=sys.stderr)
    prune(state, subs)
    state_file.write_text(json.dumps(state, indent=1, sort_keys=True))
    return 1 if failed else 0


def main():
    if sys.argv[1:] == ["--test"]:
        return 0 if send_oob(test_message()) else 1
    now = dt.datetime.now(dt.timezone.utc)
    return run(STATE_DIR, DUE_JSON, send_oob, zurich_today(now), time.time())


if __name__ == "__main__":
    sys.exit(main())
