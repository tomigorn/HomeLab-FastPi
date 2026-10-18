"""Pure avatar-picker logic: no I/O, so it is fully unit-testable."""


class UnknownAvatar(ValueError):
    pass


class AvatarTaken(ValueError):
    pass


class UnknownUser(LookupError):
    pass


def avatar_url(base, avatar_id):
    return f"{base.rstrip('/')}/img/{avatar_id}.png"


def id_from_url(base, url):
    prefix = f"{base.rstrip('/')}/img/"
    if not url or not url.startswith(prefix) or not url.endswith(".png"):
        return None
    return url[len(prefix):-len(".png")]


def _holders(users, base):
    """avatar id -> username of the user holding it."""
    held = {}
    for u in users:
        aid = id_from_url(base, (u.get("attributes") or {}).get("avatar"))
        if aid:
            held[aid] = u["username"]
    return held


def gallery_state(gallery, users, base, caller):
    """Gallery entries with status free / taken / mine. Never exposes who."""
    held = _holders(users, base)
    out = []
    for g in gallery:
        holder = held.get(g["id"])
        status = "free" if holder is None else ("mine" if holder == caller else "taken")
        out.append({"id": g["id"], "name": g["name"], "url": avatar_url(base, g["id"]),
                    "color": g["color"], "group": g.get("group"), "status": status})
    return out


def check_pick(gallery, users, base, caller, avatar_id):
    """Validate a pick; return the caller's user pk. Raises on any conflict."""
    if avatar_id not in {g["id"] for g in gallery}:
        raise UnknownAvatar(avatar_id)
    holder = _holders(users, base).get(avatar_id)
    if holder is not None and holder != caller:
        raise AvatarTaken(avatar_id)
    for u in users:
        if u["username"] == caller:
            return u["pk"]
    raise UnknownUser(caller)


def merged_attributes(current, base, avatar_id):
    merged = dict(current or {})
    merged["avatar"] = avatar_url(base, avatar_id)
    return merged
