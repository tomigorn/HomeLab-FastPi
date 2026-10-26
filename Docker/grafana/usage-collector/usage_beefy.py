#!/usr/bin/env python3
"""Runs on beefy (piped over ssh by usage_collector.py): reads Seerr requests and Jellyfin playback history through their local APIs, prints JSON. Keys are read on beefy and never leave it."""
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

SEERR = "http://localhost:5055"
JELLYFIN = "http://localhost:8096"
SEERR_SETTINGS = "/srv/appdata/seerr/settings.json"
JELLYFIN_KEY = "/home/buntu/Projects/Docker/Jellyfin/secrets/api-key"
IN_PROGRESS_SECONDS = 6 * 3600


def parse_iso(s):
    s = s.replace("Z", "+00:00")
    if "." in s:
        head, rest = s.split(".", 1)
        frac, tz = rest[:-6], rest[-6:]
        s = f"{head}.{frac[:6]}{tz}"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def seerr_user(by):
    return by.get("jellyfinUsername") or by.get("displayName") or by.get("username") or f"user{by.get('id')}"


def fetch_seerr(get, page_size=50):
    out, skip = [], 0
    while True:
        d = get(f"/api/v1/request?take={page_size}&skip={skip}&sort=added")
        res = d.get("results", [])
        for r in res:
            out.append({"id": r["id"], "user": seerr_user(r.get("requestedBy") or {}),
                        "media_type": r.get("type", "unknown"), "ts": r["createdAt"]})
        skip += page_size
        if not res or skip >= d.get("pageInfo", {}).get("results", 0):
            return out


def fetch_jellyfin(get, now=None, page_size=100):
    now = now or datetime.now(timezone.utc)
    users = {u["Id"]: u["Name"] for u in get("/Users")}
    entries, start = [], 0
    while True:
        d = get(f"/System/ActivityLog/Entries?hasUserId=true&limit={page_size}&startIndex={start}")
        items = d.get("Items", [])
        entries += [e for e in items if e.get("Type") in ("VideoPlayback", "VideoPlaybackStopped") and e.get("ItemId")]
        start += page_size
        if not items or start >= d.get("TotalRecordCount", 0):
            break
    entries.sort(key=lambda e: (parse_iso(e["Date"]), e["Id"]))
    ids = sorted({e["ItemId"] for e in entries})
    info = {}
    for i in range(0, len(ids), 40):
        for it in get("/Items?Ids=" + ",".join(ids[i:i + 40]) + "&Recursive=true").get("Items", []):
            info[it["Id"]] = it
    plays, open_ = [], {}

    def close(start_e, seconds):
        it = info.get(start_e["ItemId"])
        kind = {"Movie": "film", "Episode": "episode"}.get(it["Type"] if it else None, "other")
        if it and it.get("RunTimeTicks"):
            seconds = min(seconds, it["RunTimeTicks"] // 10**7)
        plays.append({"user": users.get(start_e["UserId"], "unknown"), "kind": kind,
                      "item": start_e["ItemId"], "seconds": int(seconds), "ts": start_e["Date"]})

    for e in entries:
        key = (e["UserId"], e["ItemId"])
        if e["Type"] == "VideoPlayback":
            if key in open_:
                close(open_[key], 0)
            open_[key] = e
        elif key in open_:
            s = open_.pop(key)
            close(s, (parse_iso(e["Date"]) - parse_iso(s["Date"])).total_seconds())
    for s in open_.values():
        if (now - parse_iso(s["Date"])).total_seconds() > IN_PROGRESS_SECONDS:
            close(s, 0)
    plays.sort(key=lambda p: parse_iso(p["ts"]))
    return plays


def http_get(base, path, headers):
    req = urllib.request.Request(base + path, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def main():
    seerr_key = json.loads(subprocess.check_output(["sudo", "cat", SEERR_SETTINGS]))["main"]["apiKey"]
    jf_key = open(JELLYFIN_KEY).read().strip()
    seerr = fetch_seerr(lambda p: http_get(SEERR, p, {"X-Api-Key": seerr_key}))
    jellyfin = fetch_jellyfin(lambda p: http_get(JELLYFIN, p, {"Authorization": f"MediaBrowser Token={jf_key}"}))
    json.dump({"seerr": seerr, "jellyfin": jellyfin}, sys.stdout)


if __name__ == "__main__":
    main()
