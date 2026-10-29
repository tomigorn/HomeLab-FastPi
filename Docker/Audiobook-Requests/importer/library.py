"""Library page (books-proxy /_hg/library/): the Audiobookshelf books a viewer may see in ABS itself, and book sizes for ABR's lists. Pure functions; importer.py fetches."""
import datetime
import re

ABS_PUBLIC = "https://audiobookshelf.holy-grail.ch/item/"
ACTIVE = ("pending", "unbound", "merge-wait")


def abs_user(users, username):
    """The viewer's ABS account: ABS usernames come from the same Holy Grail login (preferred_username), matched exactly.
    Only accounts linked to that login (hasOpenIDLink), never root: a local ABS account with the same name is not the viewer."""
    if not username:
        return None
    return next((u for u in users if u.get("username") == username and u.get("isActive", True)
                 and u.get("hasOpenIDLink") is True and u.get("type") != "root"), None)


def can_see(user, it):
    if user.get("type") == "root":
        return True
    p = user.get("permissions") or {}
    if not p.get("accessAllLibraries") and it.get("libraryId") not in (user.get("librariesAccessible") or []):
        return False
    meta = (it.get("media") or {}).get("metadata") or {}
    if meta.get("explicit") and not p.get("accessExplicitContent"):
        return False
    if not p.get("accessAllTags"):
        selected = set(user.get("itemTagsSelected") or [])
        tagged = bool(selected & set((it.get("media") or {}).get("tags") or []))
        return not tagged if p.get("selectedTagsNotAccessible") else tagged
    return True


def visible(user, libs, items_by_lib):
    books = [lib["id"] for lib in libs if lib.get("mediaType") == "book"]
    return [it for lib in books for it in items_by_lib.get(lib, []) if can_see(user, it)]


def iso_ms(ms):
    if not ms:
        return None
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def row(it, names):
    media = it.get("media") or {}
    m = media.get("metadata") or {}
    return {"id": it["id"], "title": m.get("title"), "subtitle": m.get("subtitle"), "author": m.get("authorName"),
            "narrator": m.get("narratorName"), "series": m.get("seriesName"), "duration": int(media.get("duration") or 0),
            "size": it.get("size") or media.get("size"), "added": iso_ms(it.get("addedAt")), "library": names.get(it.get("libraryId")),
            "asin": m.get("asin"), "year": m.get("publishedYear")}


def listing(user, users, libs, items_by_lib):
    if user is None:
        return {"count": 0, "items": [], "noAbsUser": True, "abs": ABS_PUBLIC}
    names = {lib["id"]: lib.get("name") for lib in libs}
    rows = [row(it, names) for it in visible(user, libs, items_by_lib)]
    return {"count": len(rows), "items": rows, "noAbsUser": False, "abs": ABS_PUBLIC}


def visible_ids(user, libs, items_by_lib):
    return {it["id"] for it in visible(user, libs, items_by_lib)} if user else set()


def sizes(items_by_lib, jobs, torrents, allowed):
    """ASIN -> bytes: the ABS item (after import and merge) if its id is in allowed, else the torrent while it still downloads.
    An ASIN of an ABS item outside allowed is left out entirely."""
    out, in_abs = {}, set()
    for items in items_by_lib.values():
        for it in items:
            asin = ((it.get("media") or {}).get("metadata") or {}).get("asin")
            if not asin:
                continue
            in_abs.add(asin)
            if asin not in out and it.get("id") in allowed:
                out[asin] = it.get("size") or (it.get("media") or {}).get("size")
    by_hash = {t.get("hash"): t.get("size") for t in torrents}
    for j in jobs.values():
        if j.get("asin") and j["asin"] not in in_abs and j.get("state") in ACTIVE and by_hash.get(j.get("hash")):
            out[j["asin"]] = by_hash[j["hash"]]
    return out


def cover_id(path):
    m = re.fullmatch(r"/library-cover/([A-Za-z0-9_-]{1,64})", path)
    return m.group(1) if m else None
