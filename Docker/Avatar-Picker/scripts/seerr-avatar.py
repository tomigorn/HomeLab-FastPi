#!/usr/bin/env python3
"""Runs on beefy as Seerr's uid, sent over ssh by avatar-sync.py. Seerr's API cannot change an avatar (PUT /api/v1/user/{id} takes only username and permissions), so this updates the one user row.
Jellyfin-linked user: new avatarVersion (the URL ?v= busts browser caches) and an empty avatar cache, so Seerr re-fetches Jellyfin's new image. OIDC user whose avatar is a picker URL: the new URL.
Usage: python3 - <holy-grail username> <picker avatar url>"""
import json
import pathlib
import re
import shutil
import sqlite3
import sys
import time

DB = "/srv/appdata/seerr/db/db.sqlite3"
CACHE = "/srv/appdata/seerr/cache/images/avatar"
PROVIDER = "holy-grail"
URL = re.compile(r"^(https://[A-Za-z0-9.-]+(?:/[A-Za-z0-9._-]+)*/img/)[a-z0-9-]+\.png$")


def refresh(db, cache, username, url, now_ms):
    m = URL.match(url)
    if not m:
        raise ValueError("not a picker avatar url")
    prefix = m.group(1)
    con = sqlite3.connect(db, timeout=15)
    try:
        row = con.execute("SELECT u.id, u.jellyfinUserId, u.avatar FROM user u JOIN linked_accounts l ON l.userId = u.id "
                          "WHERE l.provider = ? AND l.username = ?", (PROVIDER, username)).fetchone()
        if not row:
            return {"status": "no-user"}
        uid, jf_id, avatar = row
        if jf_id:
            v = str(now_ms)
            with con:
                con.execute("UPDATE user SET avatar = ?, avatarVersion = ? WHERE id = ?", (f"/avatarproxy/{jf_id}?v={v}", v, uid))
            for entry in pathlib.Path(cache).glob("*"):
                shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
            return {"status": "jellyfin-refreshed", "user": uid}
        if not (avatar or "").startswith(prefix):
            return {"status": "not-picker-avatar", "user": uid}
        if avatar == url:
            return {"status": "unchanged", "user": uid}
        with con:
            con.execute("UPDATE user SET avatar = ? WHERE id = ?", (url, uid))
        return {"status": "url-updated", "user": uid}
    finally:
        con.close()


def main(argv, db=DB, cache=CACHE):
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    print(json.dumps(refresh(db, cache, argv[0], argv[1], int(time.time() * 1000))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
