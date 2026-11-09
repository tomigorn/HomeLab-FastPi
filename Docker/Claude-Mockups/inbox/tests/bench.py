#!/usr/bin/env python3
"""Latency and resource sample: bench.py http://127.0.0.1:PORT [requests] [parallel]"""
import http.client, json, statistics, sys, threading, time
from urllib.parse import urlparse
u = urlparse(sys.argv[1]); n = int(sys.argv[2]) if len(sys.argv) > 2 else 3000; par = int(sys.argv[3]) if len(sys.argv) > 3 else 1


def run(method, path, body):
    lat = []
    def w(k):
        c = http.client.HTTPConnection(u.hostname, u.port)
        for i in range(n // par):
            b = body(k, i) if body else None
            t = time.perf_counter()
            c.request(method, path, body=b)
            c.getresponse().read()
            lat.append((time.perf_counter() - t) * 1000)
        c.close()
    t0 = time.perf_counter()
    ts = [threading.Thread(target=w, args=(k,)) for k in range(par)]
    [t.start() for t in ts]; [t.join() for t in ts]
    el = time.perf_counter() - t0
    lat.sort()
    return 'p50 %.2f ms  p95 %.2f ms  p99 %.2f ms  %.0f req/s' % (lat[len(lat) // 2], lat[int(len(lat) * .95)], lat[int(len(lat) * .99)], len(lat) / el)


print('GET  /health ', run('GET', '/health', None))
print('POST /submit ', run('POST', '/submit', lambda k, i: json.dumps({'token': 'bench-%d-%d' % (k, i % 50), 'choice': 'a', 'note': 'x' * 200})))
