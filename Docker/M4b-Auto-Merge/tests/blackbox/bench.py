#!/usr/bin/env python3
"""Measures the watcher in $WATCHER on a synthetic 700-folder library: startup, RSS, idle CPU, trigger latency, candidate-scan time. Run: run.sh IMAGE --bench"""
import os
import statistics
import time

import test_blackbox as bb


def rss_kb(pid):
    with open(f"/proc/{pid}/status") as f:
        return {l.split(":")[0]: int(l.split()[1]) for l in f if l.startswith(("VmRSS", "VmHWM"))}


def cpu_ticks(pid):
    with open(f"/proc/{pid}/stat") as f:
        v = f.read().rsplit(")", 1)[1].split()
    return int(v[11]) + int(v[12])


def main():
    os.makedirs(bb.SCRATCH, exist_ok=True)
    files = [f"Author{a:02}/Series{s}/Book{b}/{t:02}.m4b" if t == 0 else f"Author{a:02}/Series{s}/Book{b}/cover.jpg"
             for a in range(50) for s in range(3) for b in range(4) for t in range(2)]
    t = time.monotonic()
    w = bb.Watcher("bench", files=files, QUIET_SECONDS=1)
    _, tw = w.wait_for(r"  watching ", 30)
    print(f"startup to 'watching' line: {(tw - t) * 1000:.0f} ms")
    _, ti = w.wait_for(r"  trigger: nothing to merge$", 60)
    print(f"startup to first idle verdict (quiet 1 s): {ti - t:.2f} s")
    time.sleep(3)
    print(f"RSS after start: {rss_kb(w.proc.pid)}")
    c0 = cpu_ticks(w.proc.pid)
    time.sleep(60)
    print(f"idle CPU ticks in 60 s: {cpu_ticks(w.proc.pid) - c0}")
    lat = []
    start = len(w.lines)
    for n in range(5):
        last = w.write(f"New{n}/01.mp3")
        last = w.write(f"New{n}/02.mp3")
        i, tr = w.wait_for(r"  trigger: \d+ candidate", 60, start)
        lat.append(tr - last)
        w.wait_for(r"  merge run finished cleanly$", 10, i)
        start = len(w.lines)
    print(f"trigger latency after last write (quiet 1 s): p50 {statistics.median(lat):.2f} s, max {max(lat):.2f} s")
    print(f"RSS at end: {rss_kb(w.proc.pid)}")
    w.stop()


if __name__ == "__main__":
    main()
