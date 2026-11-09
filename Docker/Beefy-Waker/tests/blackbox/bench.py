#!/usr/bin/env python3
"""Latency of read-only endpoints: bench.py BASE N PATH[,METHOD[,HEADER:VALUE]] ... (never wakes)."""
import http.client
import statistics
import sys
import time
import urllib.parse


def one(base, path, method, headers):
    u = urllib.parse.urlsplit(base)
    t = time.perf_counter()
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    c.request(method, path, headers=headers)
    r = c.getresponse()
    r.read()
    c.close()
    return (time.perf_counter() - t) * 1000, r.status


def main():
    base, n = sys.argv[1], int(sys.argv[2])
    for spec in sys.argv[3:]:
        parts = spec.split(",")
        path, method = parts[0], parts[1] if len(parts) > 1 else "GET"
        headers = dict(h.split(":", 1) for h in parts[2:])
        one(base, path, method, headers)
        ms, codes = [], set()
        for _ in range(n):
            t, s = one(base, path, method, headers)
            ms.append(t)
            codes.add(s)
            time.sleep(0.05)
        ms.sort()
        print(f"{method} {path}: p50 {statistics.median(ms):.2f} ms  p95 {ms[max(0, int(n * .95) - 1)]:.2f} ms  codes {sorted(codes)}")


if __name__ == "__main__":
    main()
