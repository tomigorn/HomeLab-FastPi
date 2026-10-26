#!/usr/bin/env python3
"""Telegram warnings for the subscription deadlines in Seerr's indexer-bar/limits.toml (beefy). See README "Subscription alerts".
Stages per end date: yellow <= 30 days left, orange <= 7, red on the end date, red "expired yesterday" the day after. Each stage once per (service, end date); a renewed date starts fresh.
beefy sleeps, so the list is cached on fastpi: refreshed over ssh when beefy answers (never woken), the cache is never deleted.
Usage: subscription-alerts.py [--test]"""
import datetime as dt
import html
import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Zurich")
HERE = Path(__file__).resolve().parent
OOB = HERE / "oob-alert.sh"
STATE_DIR = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/subscription-alerts"))
REMOTE = ("beefy-direct", "/home/buntu/Projects/Docker/Seerr/indexer-bar/limits.toml")
STALE_DAYS = 7
EMOJI = {"yellow": "🟡", "orange": "🟠", "red": "🔴", "expired": "🔴"}
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
HOWTO = "After renewing: set the new date (<code>expires</code>) in <code>indexer-bar/limits.toml</code> (Seerr, beefy). The bar and these warnings follow within a minute."


def zurich_today(now):
    return now.astimezone(TZ).date()


def stage(left):
    if left > 30:
        return None
    if left > 7:
        return "yellow"
    if left > 0:
        return "orange"
    return {0: "red", -1: "expired"}.get(left)


def parse_subscriptions(text):
    try:
        subs = tomllib.loads(text).get("subscriptions")
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"invalid TOML: {e}") from e
    if not isinstance(subs, list) or not subs:
        raise ValueError("no [[subscriptions]]")
    for s in subs:
        if "name" not in s or not (s.get("lifetime") or isinstance(s.get("expires"), dt.date)):
            raise ValueError(f"subscription {s.get('name')!r}: needs expires or lifetime")
    return subs


def key(s):
    return f"{s['name']}|{s['expires'].isoformat()}"


def pending(subs, today, state):
    groups = {}
    for s in subs:
        if s.get("lifetime"):
            continue
        left = (s["expires"] - today).days
        st = stage(left)
        if st is None or st in state.get(key(s), []):
            continue
        g = groups.setdefault((st, s["expires"]), {"stage": st, "expires": s["expires"], "days": left, "items": []})
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


def render(group, cache_age_days):
    items, st, d = group["items"], group["stage"], group["days"]
    n = len(items)
    subject = html.escape(items[0]["name"]) if n == 1 else f"{n} subscriptions"
    if st == "expired":
        when = "expired yesterday"
    elif st == "red":
        when = "ends today" if n == 1 else "end today"
    else:
        when = f"{'ends' if n == 1 else 'end'} in {d} day{'' if d == 1 else 's'}"
    e = group["expires"]
    lines = [f"{EMOJI[st]} <b>{subject} {when}</b>", "",
             f"📅 {'ended ' if st == 'expired' else ''}{WEEKDAYS[e.weekday()]}, {e.day} {MONTHS[e.month - 1]} {e.year}"]
    for s in items:
        kind = f" · {html.escape(s['kind'])}" if s.get("kind") else ""
        lines.append(f"• <b>{html.escape(s['name'])}</b>{kind}")
    age = int(cache_age_days)
    if is_stale(cache_age_days):
        lines.append(f"⚠️ Subscription list is {age} days old (beefy not reachable)")
    details = HOWTO + (f"\nSubscription list is {age} day{'' if age == 1 else 's'} old." if 1 <= age and not is_stale(cache_age_days) else "")
    lines += ["", f"<blockquote expandable>{details}</blockquote>"]
    return "\n".join(lines)


def test_message():
    return "🧪 <b>Test: Example Service ends in 30 days</b>\n\n📅 Wed, 18 Nov 2026\n• <b>Example Service</b> · indexer\n\n<blockquote expandable>Test of the subscription alert path (sent by hand, not a real deadline).</blockquote>"


def cache_age_days(cache, now):
    return (now - cache.stat().st_mtime) / 86400


def refresh_cache(cache, fetch):
    text = fetch()
    if text is None:
        return False
    try:
        parse_subscriptions(text)
    except ValueError as e:
        print(f"subscription-alerts: fetched list ignored: {e}", file=sys.stderr)
        return False
    cache.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=cache.parent, prefix=".limits-")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, cache)
    return True


def fetch_from_beefy():
    host, path = REMOTE
    try:
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", host, "cat", path],
                           capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return r.stdout if r.returncode == 0 else None


def send_oob(msg):
    return subprocess.run([str(OOB), msg]).returncode == 0


def run(state_dir, fetch, send, today, now):
    cache, state_file = state_dir / "limits.toml", state_dir / "state.json"
    state_dir.mkdir(parents=True, exist_ok=True)
    refresh_cache(cache, fetch)
    if not cache.exists():
        print("subscription-alerts: no cached list and beefy not reachable", file=sys.stderr)
        return 1
    age = cache_age_days(cache, now)
    if is_stale(age):
        print(f"subscription-alerts: cached list is {int(age)} days old (beefy not reachable)", file=sys.stderr)
    try:
        subs = parse_subscriptions(cache.read_text())
    except ValueError as e:
        print(f"subscription-alerts: cached list unusable: {e}", file=sys.stderr)
        return 1
    try:
        state = json.loads(state_file.read_text())
    except (OSError, ValueError):
        state = {}
    failed = 0
    for g in pending(subs, today, state):
        if send(render(g, age)):
            mark(state, g)
            print(f"subscription-alerts: sent {g['stage']} for {', '.join(s['name'] for s in g['items'])} ({g['expires']})")
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
    return run(STATE_DIR, fetch_from_beefy, send_oob, zurich_today(now), time.time())


if __name__ == "__main__":
    sys.exit(main())
