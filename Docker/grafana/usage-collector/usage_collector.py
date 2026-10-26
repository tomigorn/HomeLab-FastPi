#!/usr/bin/env python3
"""Per-user usage into InfluxDB bucket `usage`: Seerr requests and Jellyfin plays (from beefy, skipped while it sleeps), Audiobookshelf listening (local). Idempotent: every point keeps its original timestamp, so a re-run overwrites instead of duplicating."""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
INFLUX = os.environ.get("USAGE_INFLUX_URL", "http://127.0.0.1:8086")
ORG = "myorg"
BUCKET = "usage"
TOKEN_FILE = os.environ.get("USAGE_TOKEN_FILE", os.path.join(HERE, "..", "secrets", "usage_influx_token"))
ABS_DB = os.environ.get("USAGE_ABS_DB", os.path.join(HERE, "..", "..", "audiobookshelf", "audiobookshelf", "config", "absdatabase.sqlite"))
KINDS_FILE = os.environ.get("USAGE_KINDS_FILE", os.path.expanduser("~/.local/state/usage-collector/kinds.json"))
BEEFY_SSH = "beefy-direct"
BEEFY_PROBE = ("beefy.homelab", 22)


def esc(s):
    return str(s).replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


def iso_ns(s):
    s = s.strip().replace("Z", "+00:00").replace(" +00:00", "+00:00").replace(" ", "T")
    if "." in s:
        head, rest = s.split(".", 1)
        frac, tz = rest[:-6], rest[-6:]
        s = f"{head}.{frac[:6]}{tz}"
    d = datetime.fromisoformat(s).astimezone(timezone.utc)
    return (int(d.timestamp()) * 10**6 + d.microsecond) * 1000


def beefy_lines(data):
    out = []
    for r in data.get("seerr", []):
        out.append(f"seerr_request,user={esc(r['user'])},media_type={esc(r['media_type'])} count=1i,id={int(r['id'])}i {iso_ns(r['ts'])}")
    for p in data.get("jellyfin", []):
        out.append(f"jellyfin_play,user={esc(p['user'])},kind={esc(p['kind'])} plays=1i,seconds={int(p['seconds'])}i {iso_ns(p['ts'])}")
    return out


def abs_sessions(path):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        q = ("select coalesce(u.username,'deleted user'), cast(s.timeListening as integer), s.createdAt "
             "from playbackSessions s left join users u on u.id=s.userId where s.timeListening > 0 order by s.createdAt")
        return [{"user": u, "seconds": sec, "ts": ts} for u, sec, ts in c.execute(q)]
    finally:
        c.close()


def abs_lines(rows):
    return [f"abs_listen,user={esc(r['user'])} sessions=1i,seconds={int(r['seconds'])}i {iso_ns(r['ts'])}" for r in rows]


def load_kinds(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_kinds(path, kinds):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(kinds, f)
    os.replace(tmp, path)


def apply_kinds(plays, cache):
    """A kind guessed from the activity name is replaced by the real one remembered from when the item still existed, so a later deletion does not move old points."""
    for p in plays:
        if p.get("guessed"):
            p["kind"] = cache.get(p["item"], p["kind"])
        else:
            cache[p["item"]] = p["kind"]
    return cache


def beefy_awake():
    try:
        with socket.create_connection(BEEFY_PROBE, timeout=3):
            return True
    except OSError:
        return False


def fetch_beefy():
    with open(os.path.join(HERE, "usage_beefy.py"), "rb") as f:
        script = f.read()
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", BEEFY_SSH, "python3", "-"],
                       input=script, capture_output=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"beefy collection failed (rc {r.returncode}): {r.stderr.decode(errors='replace')[-300:]}")
    return json.loads(r.stdout)


def write_influx(lines):
    token = open(TOKEN_FILE).read().strip()
    for i in range(0, len(lines), 5000):
        body = "\n".join(lines[i:i + 5000]).encode()
        req = urllib.request.Request(f"{INFLUX}/api/v2/write?org={ORG}&bucket={BUCKET}&precision=ns", data=body,
                                     headers={"Authorization": f"Token {token}"}, method="POST")
        urllib.request.urlopen(req, timeout=30).read()


def run(kinds_file=KINDS_FILE, probe=beefy_awake, fetch_beefy=fetch_beefy, abs_rows=lambda: abs_sessions(ABS_DB), write=write_influx):
    rc, lines = 0, []
    try:
        lines += abs_lines(abs_rows())
    except Exception as e:
        print(f"ERROR audiobookshelf: {e}", file=sys.stderr)
        rc = 1
    if not probe():
        print("beefy asleep, Seerr and Jellyfin skipped", file=sys.stderr)
    else:
        try:
            data = fetch_beefy()
            if kinds_file:
                cache = load_kinds(kinds_file)
                save_kinds(kinds_file, apply_kinds(data["jellyfin"], cache))
            lines += beefy_lines(data)
        except Exception as e:
            print(f"ERROR beefy: {e}", file=sys.stderr)
            rc = 1
    if lines:
        write(lines)
    print(f"wrote {len(lines)} points")
    return rc


if __name__ == "__main__":
    sys.exit(run())
