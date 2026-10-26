#!/usr/bin/env python3
# Idempotent config of prowlarr_mouse: loopback only behind prowlarr-gate, MyAnonamouse indexer (own session), qBittorrent (category abr). Never prints keys or indexer records.
#   sudo python3 Docker/mouse/scripts/prowlarr-setup.py           apply
#   sudo python3 Docker/mouse/scripts/prowlarr-setup.py --check   only verify the MAM rules and the login (exit 1 on a problem)
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

PROWLARR = "http://10.24.32.2:9697/api/v1"   # prowlarr-gate: API paths need the key, the UI only Traefik
QBIT = "http://10.24.32.2:8080/api/v2"
CONFIG_XML = Path("/mnt/seagate-red/prowlarr/config/config.xml")
SECRETS = Path(__file__).resolve().parent.parent / "secrets"
CATEGORY = "abr"
CATEGORY_PATH = "/downloads/complete/abr"

MAM_FIELDS = {
    "baseUrl": "https://www.myanonamouse.net/",
    "searchType": 1,                 # active
    "searchLanguages": [1, 37],      # English, German
    "searchInDescription": False,
    "searchInSeries": False,
    "searchInFilenames": False,
    # Owner 2026-10-26: spend a wedge on every grab that is not free for us already (Prowlarr adds fl=1 only when
    # the torrent is neither freeleech, personal freeleech nor VIP-free for a VIP user). Never gift/sendWedge/vault.
    "useFreeleechWedge": True,
}


def fill(schema, fields, mam_id):
    out = dict(schema)
    values = dict(fields, mamId=mam_id)
    out["fields"] = [dict(f, value=values.get(f["name"], f.get("value"))) for f in schema["fields"]]
    out.update(name="MyAnonamouse", enable=True, supportsRss=False, priority=25, appProfileId=1)
    return out


def problems(indexers):
    mam = [i for i in indexers if i.get("implementation") == "MyAnonamouse"]
    if not mam:
        return ["no MyAnonamouse indexer"]
    found = []
    for i in mam:
        v = {f["name"]: f.get("value") for f in i["fields"]}
        for key in ("useFreeleechWedge", "searchType"):
            if v.get(key) != MAM_FIELDS[key]:
                found.append(f"{i['name']}: {key} is {v.get(key)!r}, must be {MAM_FIELDS[key]!r}")
        if sorted(v.get("searchLanguages") or []) != sorted(MAM_FIELDS["searchLanguages"]):
            found.append(f"{i['name']}: searchLanguages is {v.get('searchLanguages')!r}")
    return found


def host_lockdown(host):
    # Forms is the only login Prowlarr 2.x has (no Basic, no headers), so Holy Grail stays the login (External) and
    # prowlarr-gate decides who reaches what: Traefik the UI, everyone else only API paths with the key.
    return dict(host, bindAddress="127.0.0.1", authenticationMethod="external", authenticationRequired="enabled")


def auth_problems(host):
    found = []
    if host.get("bindAddress") != "127.0.0.1":
        found.append(f"bindAddress is {host.get('bindAddress')!r}, must be '127.0.0.1' (prowlarr-gate in front)")
    if host.get("authenticationMethod") != "external":
        found.append(f"authenticationMethod is {host.get('authenticationMethod')!r}, must be 'external'")
    return found


def api_key():
    return re.search(r"<ApiKey>(.+?)</ApiKey>", CONFIG_XML.read_text()).group(1)


def call(key, method, path, body=None):
    req = urllib.request.Request(PROWLARR + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Api-Key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        # Validation errors echo attemptedValue (keys, passwords): print only the property and message.
        errs = json.loads(e.read() or b"[]")
        errs = errs if isinstance(errs, list) else [errs]
        raise SystemExit(f"{method} {path.split('?')[0]}: HTTP {e.code} " + "; ".join(
            f"{x.get('propertyName')}: {x.get('errorMessage') or x.get('message')}" for x in errs)) from None
    return json.loads(data) if data else None


def secret(name):
    return (SECRETS / name).read_text().strip()


def share_problems(prefs, cats):
    """MAM: 72 h seeding + ratio 1.0; we seed forever: no global and no abr share limit (-2 = global, -1 = none)."""
    found = [f"qBittorrent {k} is on" for k in ("max_ratio_enabled", "max_seeding_time_enabled",
                                                 "max_inactive_seeding_time_enabled") if prefs.get(k)]
    abr = cats.get(CATEGORY, {})
    found += [f"category {CATEGORY} {k} = {abr[k]}" for k in ("ratio_limit", "seeding_time_limit", "inactive_seeding_time_limit")
              if abr.get(k, -2) not in (-1, -2)]
    return found


def qbit_login(password):
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("Referer", "http://10.24.32.2:8080")]
    data = urllib.parse.urlencode({"username": "admin", "password": password}).encode()
    opener.open(QBIT + "/auth/login", data=data, timeout=30).read()
    if not any("SID" in c.name for c in jar):
        raise SystemExit("qBittorrent login failed")
    return opener


def qbit_shares(password):
    opener = qbit_login(password)
    with opener.open(QBIT + "/app/preferences", timeout=30) as r:
        prefs = json.load(r)
    with opener.open(QBIT + "/torrents/categories", timeout=30) as r:
        cats = json.load(r)
    return share_problems(prefs, cats)


def qbit_category(password):
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("Referer", "http://10.24.32.2:8080")]

    def post(path, **form):
        with opener.open(QBIT + path, data=urllib.parse.urlencode(form).encode(), timeout=30) as r:
            return r.read().decode()

    # 5.x answers 204 without a body; the SID cookie is the proof.
    if post("/auth/login", username="admin", password=password) not in ("Ok.", "") or not any("SID" in c.name for c in jar):
        raise SystemExit("qBittorrent login failed")
    with opener.open(QBIT + "/torrents/categories", timeout=30) as r:
        cats = json.load(r)
    if CATEGORY in cats:
        post("/torrents/editCategory", category=CATEGORY, savePath=CATEGORY_PATH)
    else:
        post("/torrents/createCategory", category=CATEGORY, savePath=CATEGORY_PATH)
    print(f"OK qBittorrent category {CATEGORY} -> {CATEGORY_PATH}")


def download_client(key, password):
    schema = next(s for s in call(key, "GET", "/downloadclient/schema") if s["implementation"] == "QBittorrent")
    values = {"host": "127.0.0.1", "port": 8080, "useSsl": False, "username": "admin", "password": password,
              "category": CATEGORY, "initialState": 0, "sequentialOrder": False, "firstAndLast": False}
    body = dict(schema, name="qBittorrent mouse", enable=True, priority=1,
                fields=[dict(f, value=values.get(f["name"], f.get("value"))) for f in schema["fields"]])
    existing = [c for c in call(key, "GET", "/downloadclient") if c["implementation"] == "QBittorrent"]
    if existing:
        body["id"] = existing[0]["id"]
        call(key, "PUT", f"/downloadclient/{body['id']}?forceSave=true", body)
    else:
        call(key, "POST", "/downloadclient?forceSave=true", body)
    print(f"OK download client qBittorrent 127.0.0.1:8080 category {CATEGORY}")


def mam_indexer(key, mam_id):
    schema = next(s for s in call(key, "GET", "/indexer/schema") if s["implementation"] == "MyAnonamouse")
    body = fill(schema, MAM_FIELDS, mam_id)
    existing = [i for i in call(key, "GET", "/indexer") if i["implementation"] == "MyAnonamouse"]
    # forceSave skips Prowlarr's test search: searches only ever run on a request.
    if existing:
        body["id"] = existing[0]["id"]
        call(key, "PUT", f"/indexer/{body['id']}?forceSave=true", body)
    else:
        call(key, "POST", "/indexer?forceSave=true", body)
    print("OK indexer MyAnonamouse (active, EN+DE, wedge on non-free grabs, no RSS)")


def main():
    key = api_key()
    if "--check" not in sys.argv:
        password = secret("qbit_pass")
        qbit_category(password)
        download_client(key, password)
        mam_indexer(key, secret("mam_prowlarr_id"))
        host = call(key, "GET", "/config/host")
        if auth_problems(host):
            call(key, "PUT", "/config/host", host_lockdown(host))
            print("OK Prowlarr on 127.0.0.1 only: docker restart prowlarr_mouse to apply")
    found = (problems(call(key, "GET", "/indexer")) + auth_problems(call(key, "GET", "/config/host"))
             + qbit_shares(secret("qbit_pass")))
    for p in found:
        print("PROBLEM", p)
    if found:
        sys.exit(1)
    print("OK MAM rules, gate and seed-forever hold")


if __name__ == "__main__":
    main()
