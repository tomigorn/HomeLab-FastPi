#!/usr/bin/env python3
"""Restarts every mouse container left in a dead network namespace after gluetun_mouse restarted, once gluetun is healthy again.

Usage: netns-watch.py           one pass (the mouse-netns-watch.timer runs it every 30 s)
       netns-watch.py --check   show each container's netns against gluetun's, change nothing (exit 1 when one is stale)
       netns-watch.py --help
Reading another uid's /proc/<pid>/ns/net needs CAP_SYS_PTRACE: the unit grants it; by hand use sudo.
"""
import html
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT = "mouse"
GLUETUN = "gluetun_mouse"
COOLDOWN = 60
MAX_ATTEMPTS = 2
STATE_FILE = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/mouse-netns-watch")) / "state.json"
OOB = Path(__file__).resolve().parents[2] / "_global" / "scripts" / "oob-alert.sh"
HINT_CHECK = f"sudo python3 {Path(__file__).resolve()} --check"


@dataclass
class Box:
    name: str
    id: str
    running: bool
    health: str | None
    netns: int | None
    target: str | None


def _box(c, netns_of):
    st = c.get("State", {})
    mode = c.get("HostConfig", {}).get("NetworkMode", "")
    pid = st.get("Pid") or 0
    return Box(c["Name"].lstrip("/"), c["Id"], bool(st.get("Running")), (st.get("Health") or {}).get("Status"),
               netns_of(pid) if pid else None, mode[len("container:"):] if mode.startswith("container:") else None)


def parse(inspected, netns_of):
    """(gluetun, dependents): dependents are the mouse project's containers that share another container's netns."""
    gluetun, deps = None, []
    for c in inspected:
        b = _box(c, netns_of)
        if b.name == GLUETUN:
            gluetun = b
        elif b.target and c.get("Config", {}).get("Labels", {}).get("com.docker.compose.project") == PROJECT:
            deps.append(b)
    return gluetun, deps


def decide(gluetun, deps, state, now):
    """(containers to restart, alert lines, new state). Nothing is restarted while gluetun is not running and healthy."""
    known = dict(state.get("containers", {}))
    actions, alerts, stale = [], [], []
    if not gluetun or not gluetun.running or gluetun.health != "healthy" or gluetun.netns is None:
        return [], [], {**state, "containers": known, "stale": state.get("stale", []), "gluetun": "down"}
    for d in deps:
        if not d.running or d.netns is None:
            continue
        entry = dict(known.get(d.name, {"attempts": 0, "last": 0.0, "alerted": False}))
        if d.target not in (gluetun.id, GLUETUN):
            stale.append(d.name)
            if not entry["alerted"]:
                alerts.append(f"{d.name}: joined a gluetun container that no longer exists, needs docker compose up -d {d.name}")
                entry["alerted"] = True
        elif d.netns == gluetun.netns:
            known.pop(d.name, None)
            continue
        else:
            stale.append(d.name)
            if entry["attempts"] >= MAX_ATTEMPTS:
                if not entry["alerted"]:
                    alerts.append(f"{d.name}: still outside gluetun's netns after {entry['attempts']} restarts")
                    entry["alerted"] = True
            elif now - entry["last"] >= COOLDOWN:
                actions.append(d.name)
                entry["attempts"] += 1
                entry["last"] = now
        known[d.name] = entry
    return actions, alerts, {**state, "containers": known, "stale": stale, "gluetun": "healthy"}


def alert_message(lines):
    body = "\n".join("• " + html.escape(line) for line in lines)
    return f"🔴 <b>mouse: VPN clients without network</b>\n\n{body}\n• check: {html.escape(HINT_CHECK)}"


def netns_inode(pid):
    try:
        return os.stat(f"/proc/{pid}/ns/net").st_ino
    except OSError:
        return None


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check, timeout=120)


def inspect_stack():
    ids = docker("ps", "-aq", "--filter", f"label=com.docker.compose.project={PROJECT}").stdout.split()
    names = ids + ([GLUETUN] if GLUETUN not in ids else [])
    out = docker("inspect", *names, check=False).stdout
    return json.loads(out) if out.strip() else []


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    tmp.replace(STATE_FILE)


def log(msg):
    print(msg, flush=True)


def check():
    g, deps = parse(inspect_stack(), netns_inode)
    if not g:
        log(f"{GLUETUN}: missing")
        return 1
    log(f"{GLUETUN}: running={g.running} health={g.health} netns={g.netns}")
    if g.netns is None:
        log(f"hint: netns unreadable, run as root: {HINT_CHECK}")
        return 1
    bad = 0
    for d in sorted(deps, key=lambda b: b.name):
        ok = d.running and d.target in (g.id, GLUETUN) and d.netns == g.netns
        bad += d.running and not ok
        log(f"  {d.name:20} {'ok' if ok else 'stopped' if not d.running else 'STALE'} netns={d.netns}")
    log("all in gluetun's netns" if not bad else f"{bad} stale; the timer restarts them once gluetun is healthy: journalctl -u mouse-netns-watch -n 20")
    return 1 if bad else 0


def run():
    state = load_state()
    g, deps = parse(inspect_stack(), netns_inode)
    was_down = state.get("gluetun") == "down"
    actions, alerts, state = decide(g, deps, state, time.time())
    if state["gluetun"] == "down" and not was_down:
        log(f"{GLUETUN} not healthy or its netns unreadable: no restarts until it is")
    state["checked"] = time.time()
    save_state(state)
    for name in actions:
        d = next(b for b in deps if b.name == name)
        log(f"{name}: netns {d.netns} != {GLUETUN} {g.netns}, restarting (attempt {state['containers'][name]['attempts']}/{MAX_ATTEMPTS})")
        try:
            r = docker("restart", name, check=False)
        except subprocess.TimeoutExpired:
            log(f"{name}: docker restart timed out")
            continue
        if r.returncode:
            log(f"{name}: docker restart failed: {r.stderr.strip()}")
    if actions:
        try:
            g2, deps2 = parse(inspect_stack(), netns_inode)
        except subprocess.TimeoutExpired:
            g2, deps2 = None, []
            log("docker inspect timed out after the restarts")
        for d in (b for b in deps2 if b.name in actions):
            log(f"{d.name}: {'back in' if g2 and d.netns == g2.netns else 'still outside'} {GLUETUN}'s netns")
    if alerts:
        for line in alerts:
            log("ALERT " + line)
        if subprocess.run([str(OOB), alert_message(alerts)]).returncode:
            log("oob alert failed to send")
    return 0


def main(argv):
    if argv in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if argv == ["--check"]:
        return check()
    if argv:
        print(f"unknown argument: {' '.join(argv)}\nhint: netns-watch.py --help", file=sys.stderr)
        return 2
    return run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
