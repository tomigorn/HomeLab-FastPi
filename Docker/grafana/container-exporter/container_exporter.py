#!/usr/bin/env python3
"""Docker container state -> Prometheus textfile exporter, plus a fallback for a dead Prometheus.

Why: on 2026-10-20 fastpi lost power twice; after boot two containers took the fixed IPs of
Traefik and wg-easy, so Traefik, CrowdSec, WireGuard and Prometheus stayed down for ~2 h and
nothing said so. Telegraf's docker input only sends running containers to InfluxDB, which no
alert rule reads, so this writes what the rules need (grafana/prometheus/rules/containers.yml):

  * container_expected_running: 1 when Docker itself would keep the container running
    (restart policy always / unless-stopped and not stopped by hand: Docker's own
    HasBeenManuallyStopped flag), so `docker compose stop` never alerts
  * container_running, container_unhealthy, container_restart_count, container_started_timestamp_seconds
  * host_last_boot_unclean: 1 when journald found a dirty journal at boot (power loss, hard reset)

The rules cannot fire while Prometheus or Alertmanager is down, which is what happened here.
So each run also checks both and, after 10 min down, sends ONE Telegram message straight to
the alert group with the Alertmanager bot (and one when they are back). It does not cover
fastpi itself being off or offline: that needs an external dead-man's switch.

Runs every minute from container-exporter.timer as root (Docker's manual-stop flag is only in
/var/lib/docker). On failure the data file stays as it was and only the status file says so.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

TEXTFILE_DIR = os.environ.get("TEXTFILE_DIR", "/var/lib/node-exporter/textfile")
STATE_PATH = os.environ.get("STATE_PATH", "/var/lib/container-exporter/state.json")
DOCKER_ROOT = os.environ.get("DOCKER_ROOT", "/var/lib/docker")
ALERTMANAGER_DIR = os.environ.get("ALERTMANAGER_DIR", "/home/pi/Projects/Docker/grafana/alertmanager")
CHECKS = json.loads(os.environ.get("WATCH_URLS") or '{"prometheus": "http://127.0.0.1:9090/-/ready", "alertmanager": "http://127.0.0.1:9093/-/healthy"}')
DOWN_AFTER_S = 600
EXPECTED_POLICIES = {"always", "unless-stopped"}


def parse_ts(s: str | None) -> float | None:
    if not s or s.startswith("0001-"):
        return None
    s = re.sub(r"\.\d+", "", s).replace("Z", "+00:00")
    return dt.datetime.fromisoformat(s).timestamp()


def rows(containers: list[dict], manually_stopped: set[str]) -> list[dict]:
    out = []
    for c in containers:
        # `docker compose run` one-offs (clamav-hostscan-run-*) are jobs, not services
        if ((c.get("Config") or {}).get("Labels") or {}).get("com.docker.compose.oneoff") == "True":
            continue
        st = c.get("State") or {}
        health = (st.get("Health") or {}).get("Status")
        policy = ((c.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name") or "no"
        out.append({
            "name": c["Name"].lstrip("/"),
            "project": ((c.get("Config") or {}).get("Labels") or {}).get("com.docker.compose.project", ""),
            "expected": int(policy in EXPECTED_POLICIES and c["Id"] not in manually_stopped),
            "running": int(st.get("Status") == "running"),
            "unhealthy": None if health is None or st.get("Status") != "running" else int(health == "unhealthy"),
            "restarts": int(c.get("RestartCount") or 0),
            "started": parse_ts(st.get("StartedAt")),
        })
    return sorted(out, key=lambda r: r["name"])


def esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render(rs: list[dict], unclean: int | None) -> str:
    lines = []

    def metric(name, help_, key):
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} gauge")
        for r in rs:
            if r[key] is not None:
                v = f"{r[key]:.0f}" if isinstance(r[key], float) else r[key]
                lines.append(f'{name}{{name="{esc(r["name"])}",project="{esc(r["project"])}"}} {v}')

    metric("container_expected_running", "1 if Docker would keep this container running (restart policy always/unless-stopped, not stopped by hand).", "expected")
    metric("container_running", "1 if the container is running.", "running")
    metric("container_unhealthy", "1 if the container healthcheck reports unhealthy (only containers with a healthcheck).", "unhealthy")
    metric("container_restart_count", "Restarts by the restart policy since the container was created.", "restarts")
    metric("container_started_timestamp_seconds", "Last start of the container.", "started")
    if unclean is not None:
        lines.append("# HELP host_last_boot_unclean 1 if the last shutdown was not clean (journald replaced a dirty journal at boot).")
        lines.append("# TYPE host_last_boot_unclean gauge")
        lines.append(f"host_last_boot_unclean {unclean}")
    return "\n".join(lines) + "\n"


def render_status(ok: bool, now: float, last_success: float | None) -> str:
    out = ["# HELP container_exporter_errors 1 if the last run failed.", "# TYPE container_exporter_errors gauge",
           f"container_exporter_errors {0 if ok else 1}"]
    if last_success:
        out += ["# HELP container_exporter_last_success_timestamp_seconds Last successful run.",
                "# TYPE container_exporter_last_success_timestamp_seconds gauge",
                f"container_exporter_last_success_timestamp_seconds {last_success:.0f}"]
    return "\n".join(out) + "\n"


def boot_was_unclean(journald_log: str) -> bool:
    return "uncleanly shut down" in journald_log


def watchdog(state: dict, now: float, ok: dict[str, bool]) -> str | None:
    since = state.setdefault("down_since", {})
    notified = state.setdefault("notified", [])
    down, back = [], []
    for svc, up in sorted(ok.items()):
        if up:
            since.pop(svc, None)
            if svc in notified:
                notified.remove(svc)
                back.append(svc)
        else:
            t = since.setdefault(svc, now)
            if now - t >= DOWN_AFTER_S and svc not in notified:
                notified.append(svc)
                down.append(f"{svc} (since {time.strftime('%H:%M', time.localtime(t))})")
    msg = []
    if down:
        items = "\n".join(f"• {d}" for d in down)
        msg.append("🔴 <b>MonitoringDown</b>\n\nNot answering for 10+ min on fastpi:\n" + items +
                   "\n• No Prometheus alert can be sent until it is back"
                   "\n<blockquote expandable>💡 Check: <code>docker ps -a | grep -E 'prometheus|alertmanager'</code>"
                   "\n<code>docker logs --tail 50 prometheus</code></blockquote>")
    if back:
        items = "\n".join(f"• {d}" for d in back)
        msg.append("✅ <b>MonitoringDown</b> · resolved\n\nBack up on fastpi:\n" + items)
    return "\n\n".join(msg) or None


def watchdog_failed(state: dict, svc: str) -> None:
    if svc in state.get("notified", []):
        state["notified"].remove(svc)


def chat_id(alertmanager_yml: str) -> str | None:
    m = re.search(r"chat_id:\s*(-?\d+)", alertmanager_yml)
    return m.group(1) if m else None


def write_atomic(path: str, text: str) -> None:
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def is_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def send_telegram(text: str) -> None:
    with open(os.path.join(ALERTMANAGER_DIR, "secrets", "telegram_bot_token")) as f:
        token = f.read().strip()
    with open(os.path.join(ALERTMANAGER_DIR, "alertmanager.yml")) as f:
        chat = chat_id(f.read())
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML"}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=20) as r:
        if r.status != 200:
            raise RuntimeError(f"telegram HTTP {r.status}")


def manually_stopped(containers: list[dict]) -> set[str]:
    out = set()
    for c in containers:
        if (c.get("State") or {}).get("Status") == "running":
            continue
        try:
            with open(os.path.join(DOCKER_ROOT, "containers", c["Id"], "config.v2.json")) as f:
                if json.load(f).get("HasBeenManuallyStopped"):
                    out.add(c["Id"])
        except (OSError, ValueError):
            pass
    return out


def unclean_this_boot(state: dict) -> int | None:
    with open("/proc/sys/kernel/random/boot_id") as f:
        boot = f.read().strip()
    if state.get("boot_id") != boot:
        p = subprocess.run(["journalctl", "-b", "0", "-t", "systemd-journald", "--no-pager", "-q", "-o", "cat"],
                           capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            return None
        state["boot_id"], state["unclean"] = boot, int(boot_was_unclean(p.stdout))
    return state["unclean"]


def load_state() -> dict:
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main() -> int:
    now = time.time()
    state = load_state()
    ok = True
    try:
        ids = subprocess.run(["docker", "ps", "-aq"], capture_output=True, text=True, timeout=30, check=True).stdout.split()
        cs = json.loads(subprocess.run(["docker", "inspect", *ids], capture_output=True, text=True,
                                       timeout=60, check=True).stdout) if ids else []
        rs = rows(cs, manually_stopped(cs))
        write_atomic(os.path.join(TEXTFILE_DIR, "container_status.prom"), render(rs, unclean_this_boot(state)))
        state["last_success"] = now
    except Exception as e:
        print(f"container export failed: {e}", file=sys.stderr)
        ok = False
    write_atomic(os.path.join(TEXTFILE_DIR, "container_exporter_status.prom"),
                 render_status(ok, now, state.get("last_success")))

    before = set(state.get("notified", []))
    msg = watchdog(state, now, {svc: is_up(url) for svc, url in CHECKS.items()})
    if msg:
        try:
            send_telegram(msg)
            print(msg.splitlines()[0])
        except Exception as e:
            print(f"telegram send failed, retry next run: {e}", file=sys.stderr)
            for svc in set(state.get("notified", [])) - before:
                watchdog_failed(state, svc)
    write_atomic(STATE_PATH, json.dumps(state))
    if ok:
        print(f"ok: containers={len(rs)} expected_down={sum(r['expected'] and not r['running'] for r in rs)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
