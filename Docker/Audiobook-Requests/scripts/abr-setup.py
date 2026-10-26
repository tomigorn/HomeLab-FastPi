#!/usr/bin/env python3
# Idempotent config of AudioBookRequest over its API: Prowlarr, auto-download, importer webhook, Audiobookshelf, OIDC login. Prints no keys.
#   sudo python3 Docker/Audiobook-Requests/scripts/abr-setup.py
# The first run logs in once as the root user (secrets/abr_root_password) and keeps an API key in secrets/abr_api_key.
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ABR = "http://10.24.25.4:8000"
HERE = Path(__file__).resolve().parent.parent
SECRETS = HERE / "secrets"
PROWLARR_XML = Path("/mnt/seagate-red/prowlarr/config/config.xml")
PROWLARR_URL = "http://10.24.25.2:9697"
# ABR searches through the importer's pass-through, which applies the release policy (importer/ranking.py).
POLICY_URL = "http://audiobook-importer:8000/prowlarr"
NEWEST_SCORES = {f"abr-newest-{i}": 60 - 10 * i for i in range(1, 6)}
ISSUER = "https://sso.holy-grail.ch/application/o/books-login/"
WEBHOOK = {
    "name": "audiobook-importer",
    "url": "http://audiobook-importer:8000/abr",
    "event_type": "onSuccessfulDownload",
    "body_type": "json",
    "headers": "{}",
    "body": json.dumps({"hash": "{torrentInfoHash}", "asin": "{bookASIN}", "title": "{bookTitle}", "authors": "{bookAuthors}",
                        "source": "{sourceTitle}", "indexer": "{indexerName}"}),
}


def env(name):
    for line in (HERE / ".env").read_text().splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1]
    return ""


def request(method, path, body=None, key=None, opener=None, form=False):
    data = None
    headers = {}
    if body is not None:
        data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(ABR + path, data=data, method=method, headers=headers)
    try:
        with (opener or urllib.request.build_opener()).open(req, timeout=60) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path}: HTTP {e.code} {e.read()[:300].decode(errors='replace')}") from None
    try:
        return json.loads(raw) if raw.strip() else None
    except ValueError:
        return None


def root_session():
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    request("POST", "/auth/login/hx-login", {"username": env("ABR_ROOT_USERNAME"),
                                              "password": (SECRETS / "abr_root_password").read_text().strip()},
            opener=opener, form=True)
    return opener


def write_secret(path, value, uid):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    os.write(fd, value.encode())
    os.close(fd)
    os.chown(path, uid, uid)


def api_key():
    path = SECRETS / "abr_api_key"
    if path.exists():
        return path.read_text().strip()
    key = request("POST", "/api/settings/account/api-keys", {"name": "abr-setup"}, opener=root_session())["key"]
    write_secret(path, key, 1000)
    print("OK API key created (secrets/abr_api_key)")
    return key


def main():
    key = api_key()
    prowlarr_key = re.search(r"<ApiKey>(.+?)</ApiKey>", PROWLARR_XML.read_text()).group(1)
    request("PUT", "/api/settings/prowlarr/base-url", {"base_url": POLICY_URL}, key)
    request("PUT", "/api/settings/prowlarr/api-key", {"api_key": prowlarr_key}, key)
    request("PUT", "/api/settings/prowlarr/categories", {"categories": [3030]}, key)
    print(f"OK Prowlarr {PROWLARR_URL} via {POLICY_URL}, category 3030 (audiobooks)")

    importer_key = SECRETS / "abr_api_key_importer"
    if not importer_key.exists():
        write_secret(importer_key, request("POST", "/api/settings/account/api-keys", {"name": "importer"}, key)["key"], 65056)
        print("OK importer API key (secrets/abr_api_key_importer)")

    session = root_session()
    for flag, score in NEWEST_SCORES.items():
        request("DELETE", f"/settings/download/hx-flags/{flag}", opener=session)
        request("POST", "/settings/download/hx-flags", {"flag": flag, "score": score}, opener=session, form=True)
    print("OK indexer flag scores abr-newest-1..5 (newest upload first)")

    download = request("GET", "/api/settings/download", key=key)
    download.update(auto_download=True, min_seeders=1)
    download.pop("indexer_flags", None)
    request("PATCH", "/api/settings/download", download, key)
    print("OK auto-download for trusted/admin requests, min 1 seeder")

    for n in request("GET", "/api/settings/notifications", key=key):
        if n["name"] == WEBHOOK["name"]:
            request("DELETE", f"/api/settings/notifications/{n['id']}", key=key)
    request("POST", "/api/settings/notifications", WEBHOOK, key)
    print("OK webhook onSuccessfulDownload -> audiobook-importer")

    # v1.10.8 takes these as form fields. Read-only ABS user `abr`. Through the importer: it asks every language library (ABR knows only one) and
    # passes nothing but GETs, so ABR's own scan-after-grab never reaches ABS (the importer scans).
    abs_key = SECRETS / "abs_api_key_abr"
    if abs_key.exists() and abs_key.read_text().strip():
        request("PUT", "/api/settings/audiobookshelf/base-url", {"base_url": "http://audiobook-importer:8000/abs"}, key, form=True)
        request("PUT", "/api/settings/audiobookshelf/api-token", {"api_token": abs_key.read_text().strip()}, key, form=True)
        libs = request("GET", "/api/settings/audiobookshelf", key=key)["abs_libraries"]
        lib = next((lib for lib in libs if "[EN]" in lib["name"]), libs[0])
        request("PUT", "/api/settings/audiobookshelf/library", {"library_id": lib["id"]}, key, form=True)
        request("PUT", "/api/settings/audiobookshelf/check-downloaded", {"check_downloaded": "true"}, key, form=True)
        print(f"OK Audiobookshelf library {lib['name']}")
    else:
        print("SKIP Audiobookshelf: no secrets/abs_api_key_abr (owner step, README)")

    client = json.loads((SECRETS / "abr_oidc_client.json").read_text())
    request("PATCH", "/api/settings/security", {
        "login_type": "oidc", "oidc_endpoint": ISSUER + ".well-known/openid-configuration",
        "oidc_client_id": client["client_id"], "oidc_client_secret": client["client_secret"],
        "oidc_scope": "openid email profile abr", "oidc_username_claim": "preferred_username",
        "oidc_group_claim": "abr_groups", "oidc_redirect_scheme": "https"}, key)
    print("OK login type OIDC (Holy Grail, books-login)")


if __name__ == "__main__":
    sys.exit(main())
