#!/usr/bin/env python3
# Idempotent config of prowlarr_mouse: MyAnonamouse indexer (own session) + qBittorrent (category abr). Never prints keys or indexer records.
#   sudo python3 Docker/mouse/scripts/prowlarr-setup.py           apply
#   sudo python3 Docker/mouse/scripts/prowlarr-setup.py --check   only verify the MAM rules (exit 1 on a problem)
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

PROWLARR = "http://10.24.32.2:9696/api/v1"
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
    "useFreeleechWedge": False,      # True would add fl=1 = spends a wedge
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
    print("OK indexer MyAnonamouse (active, EN+DE, wedges off, no RSS)")


def main():
    key = api_key()
    if "--check" not in sys.argv:
        password = secret("qbit_pass")
        qbit_category(password)
        download_client(key, password)
        mam_indexer(key, secret("mam_prowlarr_id"))
    found = problems(call(key, "GET", "/indexer"))
    for p in found:
        print("PROBLEM", p)
    if found:
        sys.exit(1)
    print("OK MAM rules hold")


if __name__ == "__main__":
    main()
