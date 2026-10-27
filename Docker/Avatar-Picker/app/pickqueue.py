"""Pending-pick queue on disk: username -> latest pick. Read by scripts/avatar-sync.py on the host."""
import json
import os
import pathlib

import core


def load(path):
    try:
        data = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(path, data):
    path = pathlib.Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    os.chmod(tmp, 0o644)
    tmp.replace(path)


def record(path, username, avatar_id, now):
    data = load(path)
    data[username] = {"avatar": avatar_id, "at": now}
    _save(path, data)


def backfill(path, users, base, now):
    """Queue the current pick of every user not in the queue yet (picks made before the queue existed)."""
    data = load(path)
    added = []
    for u in users:
        aid = core.id_from_url(base, (u.get("attributes") or {}).get("avatar"))
        if aid and u["username"] not in data:
            data[u["username"]] = {"avatar": aid, "at": now}
            added.append(u["username"])
    if added:
        _save(path, data)
    return added
