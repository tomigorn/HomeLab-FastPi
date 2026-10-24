#!/usr/bin/env python3
# Real end-to-end login + MFA against the live SSO using the canary account.
# Walks the flow executor: identification -> password -> TOTP -> success.
# Exit 0 = the auth flow completed (SSO + MFA work); non-zero = it did not.
import base64, hashlib, hmac, http.cookiejar, json, struct, sys, time, urllib.request

BASE = "https://sso.holy-grail.ch"
FLOW = "default-authentication-flow"
EXEC = f"{BASE}/api/v3/flows/executor/{FLOW}/?query="
CREDS = "/home/pi/Projects/Docker/Authentik/secrets/canary.env"


def load_creds():
    d = {}
    with open(CREDS) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d[k] = v
    return d["CANARY_USERNAME"], d["CANARY_PASSWORD"], d["CANARY_TOTP_B32"]


def totp(b32, at=None):
    key = base64.b32decode(b32)
    counter = int((at or time.time()) // 30)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    val = struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF
    return "%06d" % (val % 1000000)


def open_app(opener, url, expect):
    """With the logged-in session, follow a forward-auth app through the outpost and look for `expect` on the page."""
    try:
        with opener.open(urllib.request.Request(url), timeout=30) as resp:
            body = resp.read().decode(errors="replace")
            final = resp.geturl()
    except Exception as e:  # noqa: BLE001
        print(f"APP_FAIL: {url}: {e}")
        return 1
    if expect in body:
        print(f"APP_OK: {final} contains {expect!r}")
        return 0
    print(f"APP_FAIL: {final} lacks {expect!r}")
    return 1


def main():
    user, pw, b32 = load_creds()
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def req(method, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        r = urllib.request.Request(EXEC, data=data, method=method)
        r.add_header("Accept", "application/json")
        if data is not None:
            r.add_header("Content-Type", "application/json")
        for c in jar:
            if c.name in ("authentik_csrf", "csrftoken"):
                r.add_header("X-authentik-CSRF", c.value)
        with opener.open(r, timeout=20) as resp:
            return json.load(resp)

    d = req("GET")
    for step in range(10):
        comp = d.get("component")
        errs = d.get("response_errors")
        print(f"stage: {comp} errors: {errs}")
        if errs:
            print("LOGIN_FAIL: stage reported errors")
            return 1
        if comp == "ak-stage-identification":
            d = req("POST", {"uid_field": user})
        elif comp == "ak-stage-password":
            d = req("POST", {"password": pw})
        elif comp == "ak-stage-authenticator-validate":
            dev = next((c for c in d.get("device_challenges", []) if c.get("device_class") == "totp"), None)
            if not dev:
                print("LOGIN_FAIL: no TOTP device offered")
                return 1
            d = req("POST", {"component": "ak-stage-authenticator-validate", "selected_challenge": dev, "code": totp(b32)})
        elif comp == "ak-stage-user-login":
            # Asked only when the login stage offers "stay signed in" (remember_me_offset > 0).
            d = req("POST", {"component": "ak-stage-user-login", "remember_me": True})
        elif comp == "xak-flow-redirect" or d.get("type") == "redirect":
            print("LOGIN_OK: reached", comp or d.get("type"))
            return open_app(opener, *sys.argv[1:3]) if len(sys.argv) > 2 else 0
        else:
            print("LOGIN_FAIL: unexpected stage", comp)
            return 1
    print("LOGIN_FAIL: flow did not complete in 10 steps")
    return 1


if __name__ == "__main__":
    sys.exit(main())
