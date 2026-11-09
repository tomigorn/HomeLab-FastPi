#!/usr/bin/env python3
"""Customization checks and port_updater reattaches/stack restarts -> node-exporter textfile (customization-check.timer).

Publishes check ids only, never check output. A failed collection keeps the previous data file and flips the status file (each series lives in exactly one file, as in security_scan.py). Doc: README.md "customization-check".
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TEXTFILE = Path(os.environ.get("TEXTFILE_DIR", "/var/lib/node-exporter/textfile"))
CHECK_SCRIPT = Path(__file__).resolve().with_name("post-update-check.sh")
CHECK_TIMEOUT_S = 600
LOGS_TIMEOUT_S = 60
REATTACH_LINE = "Attempting to reattach qBittorrent/mousehole/sabnzbd to gluetun network"
STACK_LINE = "Restarting gluetun to obtain a new VPN port lease"
SUMMARY = re.compile(r"post-update: (\d+) failed, (\d+) passed")
CHECK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
LAST_SUCCESS = "customization_check_last_success_timestamp_seconds"
LAST_SUCCESS_HELP = f"# HELP {LAST_SUCCESS} Last successful collection.\n# TYPE {LAST_SUCCESS} gauge\n"


class CollectError(Exception):
    pass


def parse_checks(output: str, rc: int) -> tuple[list[str], int]:
    """(failed ids, passed count) from the script's closing lines. Anything else is a broken run, not a result."""
    lines = output.strip().splitlines()
    if rc == 0:
        summary, ids = lines[-1:], []
    elif rc == 1:
        summary = lines[-2:-1]
        if not lines or not lines[-1].startswith("FAILED: "):
            raise CollectError("no FAILED line")
        ids = lines[-1].split()[1:]
    else:
        raise CollectError(f"post-update-check exit {rc}")
    m = SUMMARY.fullmatch(summary[0]) if summary else None
    if not m:
        raise CollectError("no summary line")
    failed, passed = int(m.group(1)), int(m.group(2))
    if failed != len(ids) or failed + passed == 0:
        raise CollectError(f"summary says {failed} failed, {passed} passed, listed {len(ids)}")
    if not all(CHECK_ID.fullmatch(i) for i in ids):
        raise CollectError("malformed check id")
    return ids, passed


def count_reattaches(log: str) -> int:
    return sum(REATTACH_LINE in line for line in log.splitlines())


def count_stack_restarts(log: str) -> int:
    return sum(STACK_LINE in line for line in log.splitlines())


def render_checks(failed: list[str], passed: int, now: float) -> str:
    rows = "".join(f'customization_check_failed{{id="{i}"}} 1\n' for i in sorted(failed))
    return (
        "# HELP customization_check_failed 1 for each customization check that failed in the last run (only failed ids are listed).\n"
        f"# TYPE customization_check_failed gauge\n{rows}"
        f"# HELP customization_checks_failed Checks failed in the last run.\n# TYPE customization_checks_failed gauge\ncustomization_checks_failed {len(failed)}\n"
        f"# HELP customization_checks_passed Checks passed in the last run.\n# TYPE customization_checks_passed gauge\ncustomization_checks_passed {passed}\n"
        f'{LAST_SUCCESS_HELP}{LAST_SUCCESS}{{collector="checks"}} {now:.0f}\n'
    )


def render_reattaches(count: int, now: float, stack: int) -> str:
    return (
        "# HELP port_updater_reattaches_6h Times port_updater restarted the VPN clients to reattach them to gluetun, last 6 h.\n"
        f"# TYPE port_updater_reattaches_6h gauge\nport_updater_reattaches_6h {count}\n"
        "# HELP port_updater_stack_restarts_6h Times port_updater restarted gluetun and the VPN clients for a new port lease, last 6 h.\n"
        f"# TYPE port_updater_stack_restarts_6h gauge\nport_updater_stack_restarts_6h {stack}\n"
        f'{LAST_SUCCESS_HELP}{LAST_SUCCESS}{{collector="reattach"}} {now:.0f}\n'
    )


def render_status(collector: str, ok: bool) -> str:
    return (
        "# HELP customization_check_errors 1 if the last collection failed (the data file then holds older values).\n"
        "# TYPE customization_check_errors gauge\n"
        f'customization_check_errors{{collector="{collector}"}} {0 if ok else 1}\n'
    )


def write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def guarded(collector: str, name: str, fn) -> bool:
    try:
        text = fn()
    except (CollectError, OSError, subprocess.SubprocessError) as e:
        print(f"ERROR {collector}: {e}", file=sys.stderr)
        write_atomic(TEXTFILE / f"{name}_status.prom", render_status(collector, False))
        return False
    write_atomic(TEXTFILE / f"{name}.prom", text)
    write_atomic(TEXTFILE / f"{name}_status.prom", render_status(collector, True))
    return True


def run_checks() -> tuple[list[str], int]:
    p = subprocess.run(["bash", str(CHECK_SCRIPT), "all"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL, text=True, errors="replace", timeout=CHECK_TIMEOUT_S)
    return parse_checks(p.stdout, p.returncode)


def reattaches_6h() -> tuple[int, int]:
    p = subprocess.run(["docker", "logs", "--since", "6h", "port_updater"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True, errors="replace", timeout=LOGS_TIMEOUT_S)
    if p.returncode != 0:
        raise CollectError(f"docker logs exit {p.returncode}")
    return count_reattaches(p.stdout), count_stack_restarts(p.stdout)


def main() -> int:
    def checks() -> str:
        failed, passed = run_checks()
        print(f"checks: {len(failed)} failed, {passed} passed{': ' + ' '.join(failed) if failed else ''}")
        return render_checks(failed, passed, time.time())

    def reattach() -> str:
        n, stack = reattaches_6h()
        print(f"port_updater reattaches in 6 h: {n}, stack restarts: {stack}")
        return render_reattaches(n, time.time(), stack)

    ok = [guarded("checks", "customization_checks", checks), guarded("reattach", "port_updater_reattaches", reattach)]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
