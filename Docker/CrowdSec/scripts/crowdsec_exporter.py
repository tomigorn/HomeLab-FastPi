#!/usr/bin/env python3
"""CrowdSec -> Prometheus textfile exporter (node-exporter textfile collector).

CrowdSec's own /metrics endpoint (crowdsec:6060) covers the engine: decisions,
parsers, buckets, LAPI requests. It does NOT cover what the dashboard most
needs to answer, so this fills exactly those gaps from `cscli ... -o json`:

  * attacks per country / per scenario, as monotonic counters that survive
    CrowdSec restarts AND CrowdSec's own 7-day alert flush (persistent state)
  * attacks/attackers in the last 24h and 7d, plus the top 20 IPs of the last 24h
  * the bouncer's exact "dropped requests" (remediation-component usage metrics
    the Traefik plugin reports to the LAPI every 10 min; cscli-only otherwise)
  * when the bouncer last pulled decisions, when the community blocklist (CAPI)
    was last pulled, and the hub index age

Counting unit: ONE ALERT = ONE ATTACK. An alert is CrowdSec deciding that one IP
tripped one scenario (e.g. "probed 10 sensitive paths in 10 s"). It is not a
request count - one alert usually stands for 5-50 requests - and it is not a ban
count (a ban expires, an alert is history). Manual (cscli), community-blocklist
(capi/lists) and simulated alerts are not attacks seen here and are excluded.

Cardinality is bounded by design: country (<= ~250), scenario (~55 installed),
top-20 IPs, one bouncer. Everything stays local.

Runs every 5 min from crowdsec-exporter.timer. On failure it leaves the previous
data file untouched and only flips crowdsec_exporter_errors in the status file
(same split as Server/4-Security-Monitoring, so a stale number never reads as a
fresh zero). First run backfills from every alert still in CrowdSec's DB.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time

CONTAINER = os.environ.get("CROWDSEC_CONTAINER", "crowdsec")
TEXTFILE_DIR = os.environ.get("TEXTFILE_DIR", "/var/lib/node-exporter/textfile")
STATE_PATH = os.environ.get("STATE_PATH", "/var/lib/crowdsec-exporter/state.json")
ISO_PATH = "/usr/share/iso-codes/json/iso_3166-1.json"

# Kinds that are not "something attacked this server". kind is null on alerts
# written by CrowdSec < 1.7, which are real detections, so null is kept.
EXCLUDED_KINDS = {"cscli", "cscli-import", "capi", "papi", "console", "lists", "remediation_sync"}
RECENT_KEEP_S = 7 * 86400
TOP_N = 20


# --------------------------------------------------------------------------- pure

def parse_ts(s: str) -> float:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def is_attack(alert: dict) -> bool:
    if alert.get("kind") in EXCLUDED_KINDS or alert.get("simulated"):
        return False
    # Real scenarios are namespaced ("crowdsecurity/http-probing"); manual
    # decisions and blocklist imports carry free text ("update : +15000/-0 IPs").
    return "/" in (alert.get("scenario") or "")


def record(alert: dict) -> dict:
    src = alert.get("source") or {}
    return {
        "id": alert["id"],
        "t": parse_ts(alert["created_at"]),
        "scenario": alert.get("scenario") or "unknown",
        "ip": src.get("ip") or src.get("value") or "unknown",
        "cn": (src.get("cn") or "unknown").upper() if src.get("cn") else "unknown",
        "as": src.get("as_name") or "unknown",
    }


def ingest_alerts(state: dict, alerts: list[dict], now: float) -> int:
    """Add alerts not seen before to the persistent counters. Returns #attacks added.

    De-duplicated by alert UUID, not by id: a CrowdSec DB restore (the
    auto-update rollback does one) rewinds the id sequence, so ids get reused.
    UUIDs are kept for 8 days, longer than CrowdSec keeps alerts (7 d)."""
    seen = state.get("seen")
    legacy_last_id = None
    if seen is None:                     # state written before UUID de-dup existed
        seen, legacy_last_id = {}, state.get("last_id", 0)
    added = 0
    for a in sorted(alerts, key=lambda a: a["id"]):
        key = a.get("uuid") or f"id:{a['id']}"
        if key in seen:
            continue
        t = parse_ts(a["created_at"])
        seen[key] = t
        state["last_id"] = max(state.get("last_id", 0), a["id"])
        if (legacy_last_id is not None and a["id"] <= legacy_last_id) or not is_attack(a):
            continue
        r = record(a)
        state.setdefault("by_country", {})
        state.setdefault("by_scenario", {})
        state["by_country"][r["cn"]] = state["by_country"].get(r["cn"], 0) + 1
        state["by_scenario"][r["scenario"]] = state["by_scenario"].get(r["scenario"], 0) + 1
        state.setdefault("recent", []).append(r)
        added += 1
    state["seen"] = {k: t for k, t in seen.items() if t >= now - 8 * 86400}
    state.setdefault("last_id", 0)
    state["recent"] = [r for r in state.get("recent", []) if r["t"] >= now - RECENT_KEEP_S]
    return added


def ingest_dropped(state: dict, raw_totals: dict[str, int]) -> None:
    """Turn LAPI's aggregated 'dropped' totals into a counter that never goes down.

    The LAPI stores bouncer usage pushes and flushes old ones, so its total can
    shrink. Only increases are added; a decrease just re-baselines. First sight of
    a bouncer counts its whole stored total (backfill)."""
    seen = state.setdefault("dropped_raw", {})
    cnt = state.setdefault("dropped_total", {})
    for b, raw in raw_totals.items():
        prev = seen.get(b)
        cnt[b] = cnt.get(b, 0) + (raw if prev is None else max(0, raw - prev))
        seen[b] = raw


def esc(v: str) -> str:
    return str(v).replace("\\", "\\\\").replace("\n", " ").replace('"', '\\"')


def labels(**kw) -> str:
    return "{" + ",".join(f'{k}="{esc(v)}"' for k, v in kw.items()) + "}"


def render(state: dict, now: float, countries: dict[str, str], extra: dict) -> str:
    out: list[str] = []

    def metric(name, typ, help_, rows):
        out.append(f"# HELP {name} {help_}")
        out.append(f"# TYPE {name} {typ}")
        for lab, val in rows:
            out.append(f"{name}{lab} {val}")

    cname = lambda c: countries.get(c, "Unknown" if c == "unknown" else c)
    # Every country and every installed scenario is published, at 0 if never seen.
    # A counter series that is BORN at 1 is invisible to increase() (it has no
    # earlier sample to diff against), so the first attack from a new country
    # would never reach the map. ~250 + ~60 constant series; bounded.
    by_c = {**{c: 0 for c in countries}, "unknown": 0, **state.get("by_country", {})}
    by_s = {**{sc: 0 for sc in extra.get("scenarios", [])}, **state.get("by_scenario", {})}
    metric("crowdsec_attacks_by_country_total", "counter",
           "Attacks (CrowdSec alerts from this server's logs) by source country, ever.",
           [(labels(country=c, country_name=cname(c)), n) for c, n in sorted(by_c.items())])
    metric("crowdsec_attacks_by_scenario_total", "counter",
           "Attacks (CrowdSec alerts from this server's logs) by scenario, ever.",
           [(labels(scenario=sc), n) for sc, n in sorted(by_s.items())])

    recent = state.get("recent", [])
    rows_a, rows_ip = [], []
    for w, secs in (("24h", 86400), ("7d", 7 * 86400)):
        sel = [r for r in recent if r["t"] >= now - secs]
        rows_a.append((labels(window=w), len(sel)))
        rows_ip.append((labels(window=w), len({r["ip"] for r in sel})))
    metric("crowdsec_attacks_recent", "gauge", "Attacks in the trailing window (from CrowdSec's alert DB, independent of Prometheus history).", rows_a)
    metric("crowdsec_attackers_recent", "gauge", "Distinct attacking IPs in the trailing window.", rows_ip)

    day = [r for r in recent if r["t"] >= now - 86400]
    by_sc = collections.Counter(r["scenario"] for r in day)
    metric("crowdsec_attacks_24h_by_scenario", "gauge", "Attacks in the last 24h by scenario.",
           [(labels(scenario=s), n) for s, n in sorted(by_sc.items())])
    by_ip: dict[str, list[dict]] = collections.defaultdict(list)
    for r in day:
        by_ip[r["ip"]].append(r)
    top = sorted(by_ip.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:TOP_N]
    rows = []
    for ip, rs in top:
        last = max(rs, key=lambda r: r["t"])
        sc = collections.Counter(r["scenario"] for r in rs).most_common(1)[0][0]
        rows.append((labels(ip=ip, country=last["cn"], country_name=cname(last["cn"]),
                            as_name=last["as"] or "unknown", scenario=sc), len(rs)))
    metric("crowdsec_top_attacker_attacks_24h", "gauge",
           f"Top {TOP_N} attacking IPs of the last 24h: attacks each (scenario = most frequent).", rows)

    metric("crowdsec_bouncer_dropped_requests_total", "counter",
           "Requests the bouncer refused (LAPI remediation-component usage metrics, reported every 10 min).",
           [(labels(bouncer=b), n) for b, n in sorted(state.get("dropped_total", {}).items())])
    if extra.get("bouncer_last_pull"):
        metric("crowdsec_bouncer_last_pull_timestamp_seconds", "gauge",
               "Last time the bouncer pulled decisions from the LAPI.",
               [(labels(bouncer=b), f"{t:.0f}") for b, t in sorted(extra["bouncer_last_pull"].items())])
    if extra.get("capi_last_pull") is not None:
        metric("crowdsec_capi_last_pull_timestamp_seconds", "gauge",
               "Last community-blocklist (CAPI) pull, from the newest 'update' alert of kind capi.",
               [("", f"{extra['capi_last_pull']:.0f}")])
    if extra.get("hub_index_mtime") is not None:
        metric("crowdsec_hub_index_timestamp_seconds", "gauge",
               "mtime of the hub index (refreshed by cscli hub update).", [("", f"{extra['hub_index_mtime']:.0f}")])
    if extra.get("hub_items_not_ok") is not None:
        metric("crowdsec_hub_items_not_ok", "gauge",
               "Installed hub items whose status is not plain 'enabled' (update available, tainted, ...).",
               [("", extra["hub_items_not_ok"])])
    return "\n".join(out) + "\n"


def render_status(ok: bool, now: float, last_success: float | None) -> str:
    lines = [
        "# HELP crowdsec_exporter_errors 1 if the last collection failed (data file then holds older values).",
        "# TYPE crowdsec_exporter_errors gauge",
        f"crowdsec_exporter_errors {0 if ok else 1}",
        "# HELP crowdsec_exporter_last_success_timestamp_seconds Last successful collection.",
        "# TYPE crowdsec_exporter_last_success_timestamp_seconds gauge",
        f"crowdsec_exporter_last_success_timestamp_seconds {(last_success or 0):.0f}",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- I/O

def cscli(*args: str):
    p = subprocess.run(["docker", "exec", CONTAINER, "cscli", *args, "-o", "json"],
                       capture_output=True, text=True, timeout=120, check=True)
    return json.loads(p.stdout or "null")


def write_atomic(path: str, text: str) -> None:
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def load_countries() -> dict[str, str]:
    try:
        with open(ISO_PATH) as f:
            return {c["alpha_2"]: c.get("common_name") or c["name"] for c in json.load(f)["3166-1"]}
    except OSError:
        return {}


def collect(state: dict, now: float) -> dict:
    # New alerts: everything on first run (backfill), afterwards a window that
    # overlaps the previous run generously; ids de-duplicate.
    if "last_id" not in state:
        alerts = cscli("alerts", "list", "-l", "0")
    else:
        hours = max(2, int((now - state.get("last_run", now)) / 3600) + 2)
        alerts = cscli("alerts", "list", "-l", "0", "--since", f"{hours}h")
    ingest_alerts(state, alerts or [], now)

    raw: dict[str, int] = collections.defaultdict(int)
    for name, origins in ((cscli("metrics", "show", "bouncers") or {}).get("bouncers") or {}).items():
        base = name.split("@")[0]
        for _origin, kinds in (origins or {}).items():
            raw[base] += int(((kinds or {}).get("dropped") or {}).get("request", 0))
    ingest_dropped(state, dict(raw))

    extra: dict = {"bouncer_last_pull": {}}
    for b in cscli("bouncers", "list") or []:
        if b.get("last_pull"):
            base = b["name"].split("@")[0]
            t = parse_ts(b["last_pull"])
            extra["bouncer_last_pull"][base] = max(t, extra["bouncer_last_pull"].get(base, 0))
    capi = [parse_ts(a["created_at"]) for a in (cscli("alerts", "list", "-a", "--kind", "capi", "-l", "1") or [])]
    extra["capi_last_pull"] = max(capi) if capi else None
    p = subprocess.run(["docker", "exec", CONTAINER, "stat", "-c", "%Y", "/etc/crowdsec/hub/.index.json"],
                       capture_output=True, text=True, timeout=30)
    extra["hub_index_mtime"] = float(p.stdout.strip()) if p.returncode == 0 and p.stdout.strip() else None
    hub = cscli("hub", "list") or {}
    extra["scenarios"] = [i["name"] for i in (hub.get("scenarios") or []) if i.get("name")]
    extra["hub_items_not_ok"] = sum(1 for items in hub.values() for i in (items or [])
                                    if (i.get("status") or "enabled") != "enabled")
    return extra


def main() -> int:
    now = time.time()
    try:
        with open(STATE_PATH) as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {}
    data_path = os.path.join(TEXTFILE_DIR, "crowdsec.prom")
    status_path = os.path.join(TEXTFILE_DIR, "crowdsec_status.prom")
    try:
        extra = collect(state, now)
        text = render(state, now, load_countries(), extra)
    except Exception as e:  # noqa: BLE001 - any failure: keep old data, flag it
        print(f"crowdsec exporter: collection failed: {e!r}", file=sys.stderr)
        write_atomic(status_path, render_status(False, now, state.get("last_success")))
        return 1
    state["last_run"] = now
    state["last_success"] = now
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    write_atomic(STATE_PATH, json.dumps(state, separators=(",", ":")))
    write_atomic(data_path, text)
    write_atomic(status_path, render_status(True, now, now))
    print(f"ok: last_id={state['last_id']} countries={len(state.get('by_country', {}))} "
          f"attacks={sum(state.get('by_country', {}).values())} recent={len(state.get('recent', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
