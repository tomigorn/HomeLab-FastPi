#!/usr/bin/env python3
# Real canary login (password + TOTP) through Holy Grail, then ABR's own OIDC login; exit 0 only if ABR shows a logged-in page. Run via verify-login.sh.
import sys

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
