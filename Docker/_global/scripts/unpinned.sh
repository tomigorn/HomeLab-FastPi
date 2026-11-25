#!/usr/bin/env bash
# Reads `docker inspect` JSON on stdin, prints "name/network ..." for every network without a pinned IPv4 (host, none, container:, service: skipped). Empty output = all pinned.
python3 -I -c '
import json, sys
out = []
for c in json.load(sys.stdin):
    for net, d in (c["NetworkSettings"].get("Networks") or {}).items():
        if net in ("host", "none") or net.startswith(("container:", "service:")):
            continue
        if not ((d.get("IPAMConfig") or {}).get("IPv4Address")):
            out.append(c["Name"].lstrip("/") + "/" + net)
print(" ".join(out))
'
