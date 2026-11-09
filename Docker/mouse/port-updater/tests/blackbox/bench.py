"""Startup time, web latency, RSS and idle CPU of the service against the fakes (same env as the black-box suite)."""
import os
import statistics
import time
import unittest

import test_blackbox as tb


def tree_pids(root):
    pids, todo = [], [root]
    while todo:
        p = todo.pop()
        pids.append(p)
        try:
            with open(f"/proc/{p}/task/{p}/children") as f:
                todo += [int(c) for c in f.read().split()]
        except OSError:
            pass
    return pids


def rss_kb(pids):
    total = 0
    for p in pids:
        try:
            with open(f"/proc/{p}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        total += int(line.split()[1])
        except OSError:
            pass
    return total


def cpu_ticks(pids):
    total = 0
    for p in pids:
        try:
            with open(f"/proc/{p}/stat") as f:
                fields = f.read().rsplit(")", 1)[1].split()
                total += int(fields[11]) + int(fields[12])
        except OSError:
            pass
    return total


class Bench(tb.Web):
    def test_bench(self):
        t0 = time.monotonic()
        self.wait_web()
        startup = time.monotonic() - t0
        u, p = self.web_user, self.web_pass
        res = {}
        for path in ("/", "/api/history", "/nope"):
            lat = []
            for _ in range(200):
                s = time.perf_counter()
                tb.http("GET", path, u, p)
                lat.append((time.perf_counter() - s) * 1000)
            lat.sort()
            res[path] = (statistics.median(lat), lat[int(len(lat) * 0.95)])
        with self.world.lock:
            self.world.qbit_available = True
        self.wait_log(r"^Port (OK|updated)", 90)
        pids = tree_pids(self.proc.pid)
        c0, w0 = cpu_ticks(pids), time.monotonic()
        time.sleep(30)
        pids = tree_pids(self.proc.pid)
        cpu = (cpu_ticks(pids) - c0) / os.sysconf("SC_CLK_TCK") / (time.monotonic() - w0) * 100
        print(f"\nBENCH startup_to_web_s={startup:.3f} rss_kb={rss_kb(pids)} procs={len(pids)} cpu_idle_pct={cpu:.2f} (CHECK_INTERVAL=4 SESSION_CHECK_INTERVAL=1)")
        for path, (p50, p95) in res.items():
            print(f"BENCH latency {path} p50_ms={p50:.2f} p95_ms={p95:.2f}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
