#!/usr/bin/env python3
"""MyAnonamouse bonus-points estimator. Makes no call to MyAnonamouse: last known balance + earning rate = estimate. See README "mam-points".
Usage: mam-points status | set N [--rate R] | spent N | reset | rate R | check [--preview]  (preview sends a sample yellow alert with made-up points)"""
import datetime as dt
import html
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Zurich")
HERE = Path(__file__).resolve().parent
OOB = HERE / "oob-alert.sh"
STATE_FILE = Path(os.environ.get("MAM_POINTS_STATE", "/var/lib/mam-points/state.json"))
PROM_FILE = Path(os.environ.get("MAM_POINTS_PROM", "/var/lib/node-exporter/textfile/mam_points.prom"))
CAP = 99999
YELLOW = 90000
THRESHOLDS = {"yellow": YELLOW, "red": CAP}
EMOJI = {"yellow": "🟡", "red": "🔴"}
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
HOWTO = ("Update after checking the balance on MAM or spending points:\n"
         "<code>mam-points set 51655</code> (current balance)\n"
         "<code>mam-points spent 25000</code> (after spending)\n"
         "<code>mam-points rate 309.9</code> (new points per hour)\n"
         "<code>mam-points status</code>")


def parse_number(text):
    try:
        v = float(str(text).replace(",", "").replace("'", "").strip())
    except ValueError:
        raise ValueError(f"not a number: {text!r}") from None
    if not math.isfinite(v):
        raise ValueError(f"not a number: {text!r}")
    return v


def updated(s):
    return dt.datetime.fromisoformat(s["updated"])


def estimate(s, now):
    hours = max(0.0, (now - updated(s)).total_seconds() / 3600)
    return min(CAP, s["points"] + s["rate"] * hours)


def crossing(s, threshold):
    return updated(s) + dt.timedelta(hours=(threshold - s["points"]) / s["rate"])


def new_state(points, rate, now, epoch):
    return {"points": points, "rate": rate, "updated": now.isoformat(), "epoch": epoch, "alerted": []}


def _require(s):
    if s is None:
        raise ValueError("no state yet: run mam-points set N --rate R")
    return s


def _balance(v):
    if not 0 <= v <= CAP:
        raise ValueError(f"balance must be between 0 and {CAP:,}")
    return v


def _rate(v):
    if not (math.isfinite(v) and v > 0):
        raise ValueError("rate must be greater than 0")
    return v


def cmd_set(s, points, now, rate=None):
    _balance(points)
    if rate is None:
        rate = _require(s)["rate"]
    return new_state(points, _rate(rate), now, (s["epoch"] if s else 0) + 1)


def cmd_reset(s, now):
    return cmd_set(s, 0, now)


def cmd_spent(s, amount, now):
    s = _require(s)
    if amount <= 0:
        raise ValueError("amount must be greater than 0")
    est = estimate(s, now)
    if amount > est:
        raise ValueError(f"cannot spend more than the estimate ({int(est):,})")
    return new_state(est - amount, s["rate"], now, s["epoch"] + 1)


def cmd_rate(s, rate, now):
    s = _require(s)
    return new_state(estimate(s, now), _rate(rate), now, s["epoch"] + 1)


def due(s, now):
    est = estimate(s, now)
    reached = [k for k, t in THRESHOLDS.items() if est >= t and k not in s["alerted"]]
    return reached[-1:]


def fmt_when(t):
    z = t.astimezone(TZ)
    return f"{WEEKDAYS[z.weekday()]}, {z.day} {MONTHS[z.month - 1]} {z.year} {z:%H:%M}"


def fmt_days(hours):
    d = hours / 24
    return "less than a day" if d < 1 else f"about {round(d)} day{'' if round(d) == 1 else 's'}"


def render(stage, s, now, preview=False):
    est = int(estimate(s, now))
    prefix = "🧪 Preview: " if preview else ""
    until_cap = (CAP - estimate(s, now)) / s["rate"]
    if stage == "yellow":
        title = f"≈ {est:,} MAM points, {fmt_days(until_cap)} until the cap of {CAP:,}"
        cap_line = f"📅 cap reached ≈ {fmt_when(crossing(s, CAP))}"
        bullets = [f"• <b>≈ {est:,}</b> points, +{s['rate']:g}/h", "• Spend some before the cap"]
        crossed = f"{YELLOW:,} crossed ≈ {fmt_when(crossing(s, YELLOW))}"
    else:
        title = f"≈ {CAP:,} MAM points, points are being wasted"
        cap_line = f"📅 cap reached ≈ {fmt_when(crossing(s, CAP))}"
        bullets = [f"• <b>≈ {CAP:,}</b> points, no more are earned", "• Spend them now"]
        crossed = f"cap of {CAP:,} crossed ≈ {fmt_when(crossing(s, CAP))}"
    details = (f"Estimate only, no contact with MAM: {s['points']:,.0f} points at {s['rate']:g}/h as of {fmt_when(updated(s))}. {crossed}.\n" + HOWTO)
    return "\n".join([f"{prefix}{EMOJI[stage]} <b>{html.escape(title)}</b>", "", cap_line, *bullets, "",
                      f"<blockquote expandable>{details}</blockquote>"])


def check(s, now, send):
    for stage in due(s, now):
        if send(render(stage, s, now)):
            s = dict(s, alerted=sorted(set(s["alerted"]) | {k for k, t in THRESHOLDS.items() if t <= THRESHOLDS[stage]}))
            print(f"mam-points: sent {stage}")
        else:
            print(f"mam-points: send failed for {stage}", file=sys.stderr)
    return s


def status_text(s, now):
    est = estimate(s, now)
    lines = [f"Estimate now:   ≈ {int(est):,} points (cap {CAP:,})",
             f"Last known:     {s['points']:,.0f} points at {fmt_when(updated(s))}",
             f"Rate:           {s['rate']:g} points/hour ({s['rate'] * 24:,.0f}/day)"]
    for label, thr in (("90,000", YELLOW), (f"cap {CAP:,}", CAP)):
        if est >= thr:
            lines.append(f"{label + ':':<15} reached ≈ {fmt_when(crossing(s, thr))}")
        else:
            lines.append(f"{label + ':':<15} ≈ {fmt_when(crossing(s, thr))} ({fmt_days((thr - est) / s['rate'])})")
    return "\n".join(lines)


def load(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _atomic(path, text):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".mam-")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def save(path, s):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _atomic(path, json.dumps(s, indent=1, sort_keys=True))


def write_prom(path, s, now):
    path = Path(path)
    if not path.parent.is_dir():
        return
    _atomic(path, "\n".join([
        "# TYPE mam_points_estimated gauge", f"mam_points_estimated {int(estimate(s, now))}",
        "# TYPE mam_points_rate_per_hour gauge", f"mam_points_rate_per_hour {s['rate']:g}",
        "# TYPE mam_points_last_update_timestamp_seconds gauge",
        f"mam_points_last_update_timestamp_seconds {int(updated(s).timestamp())}", ""]))


def send_oob(msg):
    return subprocess.run([str(OOB), msg]).returncode == 0


def main(argv):
    now = dt.datetime.now(dt.timezone.utc)
    s = load(STATE_FILE)
    cmd, args = (argv[0] if argv else "status"), argv[1:]
    try:
        if cmd == "status" and not args:
            print(status_text(_require(s), now))
            return 0
        if cmd == "check" and args in ([], ["--preview"]):
            s = _require(s)
            if args:
                demo = new_state(YELLOW + 100, s["rate"], now - dt.timedelta(hours=100 / s["rate"]), s["epoch"])
                return 0 if send_oob(render("yellow", demo, now, preview=True)) else 1
            s = check(s, now, send_oob)
            save(STATE_FILE, s)
            write_prom(PROM_FILE, s, now)
            return 0
        if cmd == "set" and len(args) in (1, 3) and (len(args) == 1 or args[1] == "--rate"):
            s = cmd_set(s, parse_number(args[0]), now, parse_number(args[2]) if len(args) == 3 else None)
        elif cmd == "spent" and len(args) == 1:
            s = cmd_spent(s, parse_number(args[0]), now)
        elif cmd == "reset" and not args:
            s = cmd_reset(s, now)
        elif cmd == "rate" and len(args) == 1:
            s = cmd_rate(s, parse_number(args[0]), now)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except ValueError as e:
        print(f"mam-points: {e}", file=sys.stderr)
        return 2
    save(STATE_FILE, s)
    write_prom(PROM_FILE, s, now)
    print(status_text(s, now))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
