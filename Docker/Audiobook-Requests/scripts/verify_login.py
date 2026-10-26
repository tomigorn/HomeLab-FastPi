#!/usr/bin/env python3
# Real canary login (password + TOTP) through Holy Grail, then ABR's own OIDC login; exit 0 only if ABR shows a logged-in page. Run via verify-login.sh.
import os
import socket
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
    missing = [t for t in (expect, "Movies / Series") if t not in body]
    if not missing:
        print(f"APP_OK: {final} is logged in, navbar has the Seerr link")
        return 0
    print(f"APP_FAIL: {final} lacks {missing}")
    return 1


clt.open_app = open_abr
sys.argv = [sys.argv[0], URL, "/auth/logout"]
sys.exit(clt.main())
