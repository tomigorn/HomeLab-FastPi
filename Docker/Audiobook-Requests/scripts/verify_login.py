#!/usr/bin/env python3
# Real canary login (password + TOTP) through Holy Grail, then ABR's own OIDC login; exit 0 only if ABR shows a logged-in page with the Seerr link script and the All requests page lists others' requests. Run via verify-login.sh.
# QUOTA_ASINS="a1 a2 ... a6": also request those books as the canary (auto-download must be off) and expect the 6th to be refused.
import json
import os
import socket
import urllib.request
import subprocess
import sys

# PUBLIC=1: resolve *.holy-grail.ch through 1.1.1.1 (Cloudflare tunnel) instead of AdGuard's LAN answer.
if os.environ.get("PUBLIC") == "1":
    _orig = socket.getaddrinfo

    def _public(host, *args, **kwargs):
        if str(host).endswith(".holy-grail.ch"):
            ip = subprocess.run(["dig", "+short", "@1.1.1.1", host], capture_output=True, text=True).stdout.split()[-1]
            return _orig(ip, *args, **kwargs)
        return _orig(host, *args, **kwargs)

    socket.getaddrinfo = _public

    # Cloudflare answers 403 to the default Python-urllib user agent.
    import urllib.request
    _build = urllib.request.build_opener

    def _opener(*handlers):
        o = _build(*handlers)
        o.addheaders = [("User-Agent", "Mozilla/5.0 (holy-grail login check)")]
        return o

    urllib.request.build_opener = _opener

sys.path.insert(0, "/home/pi/Projects/Docker/Authentik/scripts")
import canary_login_test as clt  # noqa: E402

URL = "https://books.holy-grail.ch/"


def open_abr(opener, url, expect):
    try:
        with opener.open(url, timeout=30) as r:
            first = r.read().decode(errors="replace")
            print(f"ABR_STEP1: {r.geturl().split('?')[0]} {'Redirecting...' in first and 'oidc redirect page' or 'other page'}")
        with opener.open(url, timeout=30) as r:
            body = r.read().decode(errors="replace")
            final = r.geturl().split("?")[0]
    except Exception as e:  # noqa: BLE001
        print(f"APP_FAIL: {e}")
        return 1
    base = url.rstrip("/")
    try:
        with opener.open(base + "/_hg/links.js", timeout=30) as r:
            script = r.read().decode(errors="replace")
        with opener.open(base + "/search?q=yellow+wallpaper", timeout=60) as r:
            search = r.read().decode(errors="replace")
        with opener.open(base + "/_hg/requests/", timeout=30) as r:
            page = r.read().decode(errors="replace")
        with opener.open(base + "/_hg/requests/data.json", timeout=60) as r:
            rows = json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        print(f"APP_FAIL: {e}")
        return 1
    checks = {"logged in": expect in body, "link script on page": "/_hg/links.js" in body,
              "link script": "Movies / Series" in script, "search works": "Yellow Wallpaper" in search,
              "all requests page": "All requests" in page and "All requests" in script,
              "others' requests with names": any(r.get("requested_by") not in (None, "", "canary-test") for r in rows)}
    print("APP_CHECKS:", checks)
    if not all(checks.values()):
        print(f"APP_FAIL: {final}")
        return 1
    print(f"APP_OK: {final} logged in, Seerr link injected, search works")
    asins = os.environ.get("QUOTA_ASINS", "").split()
    for n, asin in enumerate(asins, 1):
        req = urllib.request.Request(f"{base}/request/hx-add/{asin}", data=b"", method="POST")
        with opener.open(req, timeout=60) as r:
            refused = "Limit reached" in r.read().decode(errors="replace")
        print(f"QUOTA request {n}: {'refused' if refused else 'accepted'}")
        if refused != (n > 5):
            print("QUOTA_FAIL")
            return 1
    if asins:
        print("QUOTA_OK: 5 accepted, the 6th refused")
    return 0
    return 1


clt.open_app = open_abr
sys.argv = [sys.argv[0], URL, "/auth/logout"]
sys.exit(clt.main())
