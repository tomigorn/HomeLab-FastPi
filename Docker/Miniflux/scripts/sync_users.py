#!/usr/bin/env python3
"""Gives every non-admin Miniflux user the feeds and categories of MINIFLUX_ADMIN and keeps them in sync (idempotent).

Usage: Docker/Miniflux/scripts/sync_users.py [-h|--help]
Adds what the admin has, moves synced feeds to the admin's category, removes synced feeds and empty synced categories the admin dropped.
A user's own feeds and categories are never touched; integrations (Telegram) are never copied.
Every user (admin included) gets a "Tech stack" link in the header menu (custom JavaScript between LINK_START and LINK_END; the user's own custom JavaScript stays).
Each user is reached with its own API key "feed-sync" (derived from secrets/api_key, row upserted over psql when missing).
State (which feeds came from the sync): secrets/feed_sync_state.json. Runs every 5 minutes by miniflux-feed-sync.timer.
"""
import hashlib
import hmac
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error

from subscribe import ROOT, call, masked

TIMEOUT = 150
HEX = re.compile(r"^[0-9a-f]+$")
LINK_START = "/* homelab-about */"   # marker kept from the first version so old blocks are replaced
LINK_END = "/* /homelab-about */"
LINK_JS = LINK_START + """
(() => {
  const menu = document.getElementById("header-menu");
  if (!menu || menu.querySelector("[data-homelab-techstack]")) return;
  const li = document.createElement("li");
  li.dataset.homelabTechstack = "";
  const a = document.createElement("a");
  a.href = "/techstack";
  a.textContent = "Tech stack";
  li.append(a);
  menu.append(li);
})();
""" + LINK_END
LINK_BLOCK = re.compile(re.escape(LINK_START) + ".*?" + re.escape(LINK_END) + r"\n?", re.S)


def with_techstack_link(custom_js):
    own = LINK_BLOCK.sub("", custom_js or "").strip()
    return LINK_JS + ("\n" + own if own else "")


def user_key(admin_key, user_id):
    return hmac.new(admin_key.encode(), f"feed-sync:{user_id}".encode(), hashlib.sha256).hexdigest()


def upsert_sql(rows):
    values = []
    for uid, token in rows:
        if not HEX.match(token):
            raise ValueError("token must be hex")
        values.append(f"({int(uid)}, '{token}', 'feed-sync')")
    return ("INSERT INTO api_keys (user_id, token, description) VALUES " + ", ".join(values)
            + " ON CONFLICT (user_id, description) DO UPDATE SET token = EXCLUDED.token;")


def run_sql(sql, run=subprocess.run):
    run(["docker", "exec", "-i", "miniflux-db", "psql", "-q", "-v", "ON_ERROR_STOP=1", "-U", "miniflux", "-d", "miniflux"],
        input=sql.encode(), check=True, capture_output=True)


def load_state(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def save_state(path, state):
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def error_text(e):
    try:
        return masked(e.read().decode())[:200]
    except Exception:
        return ""


def sync_user(call, key, name, admin_feeds, admin_cats, synced, lines):
    feeds_synced, cats_synced = set(synced.get("feeds", [])), set(synced.get("categories", []))
    cats = {c["title"]: c["id"] for c in call("GET", "/categories", key)}
    feeds = {f["feed_url"]: (f["id"], f["category"]["title"]) for f in call("GET", "/feeds", key)}
    added = moved = removed = 0
    for title in sorted(admin_cats - cats.keys()):
        cats[title] = call("POST", "/categories", key, {"title": title})["id"]
        cats_synced.add(title)
        lines.append(f"{name}: category {title}")
    for url, category in sorted(admin_feeds.items()):
        if url not in feeds:
            lines.append(f"{name}: subscribe {category}: {masked(url)}")
            try:
                fid = call("POST", "/feeds", key, {"feed_url": url, "category_id": cats[category]}, timeout=TIMEOUT)["feed_id"]
            except urllib.error.HTTPError as e:
                lines.append(f"  FAILED {e.code}: {error_text(e)}")
                continue
            feeds[url] = (fid, category)
            feeds_synced.add(url)
            added += 1
        elif url in feeds_synced and feeds[url][1] != category:
            call("PUT", f"/feeds/{feeds[url][0]}", key, {"category_id": cats[category]})
            feeds[url] = (feeds[url][0], category)
            moved += 1
    for url in sorted(feeds_synced - admin_feeds.keys()):
        if url in feeds:
            lines.append(f"{name}: unsubscribe {masked(url)}")
            call("DELETE", f"/feeds/{feeds.pop(url)[0]}", key)
            removed += 1
    for title in sorted(cats_synced - admin_cats):
        if title in cats and not any(c == title for _, c in feeds.values()):
            lines.append(f"{name}: remove category {title}")
            call("DELETE", f"/categories/{cats[title]}", key)
    lines.append(f"{name}: {len(admin_feeds)} feeds, {added} new, {moved} moved, {removed} removed")
    return {"feeds": sorted(feeds_synced & admin_feeds.keys() & feeds.keys()), "categories": sorted(cats_synced & admin_cats)}


def sync(call, admin_key, admin_name, state, ensure_keys):
    """Returns (new state, output lines). A line starting with ERROR marks a user that could not be synced."""
    lines = []
    admin_feeds = {f["feed_url"]: f["category"]["title"] for f in call("GET", "/feeds", admin_key)}
    admin_cats = {c["title"] for c in call("GET", "/categories", admin_key)}
    everyone = call("GET", "/users", admin_key)
    users = [u for u in everyone if not u["is_admin"] and u["username"] != admin_name]
    missing = []
    for u in users:
        try:
            call("GET", "/me", user_key(admin_key, u["id"]))
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            missing.append((u["id"], user_key(admin_key, u["id"])))
    if missing:
        ensure_keys(missing)
    new_state = {}
    for u in users:
        uid = str(u["id"])
        try:
            new_state[uid] = sync_user(call, user_key(admin_key, u["id"]), u["username"], admin_feeds, admin_cats, state.get(uid, {}), lines)
        except urllib.error.HTTPError as e:
            lines.append(f"ERROR {u['username']}: {e.code} {error_text(e)}")
            if uid in state:
                new_state[uid] = state[uid]
    if not users:
        lines.append("no other users")
    for u in everyone:
        js = with_techstack_link(u.get("custom_js", ""))
        if js != u.get("custom_js"):
            call("PUT", f"/users/{u['id']}", admin_key, {"custom_js": js})
            lines.append(f"{u['username']}: tech stack link")
    return new_state, lines


def main():
    if sys.argv[1:]:
        print(__doc__.strip())
        sys.exit(0 if {"-h", "--help"} & set(sys.argv[1:]) else 2)
    admin_key = (ROOT / "secrets" / "api_key").read_text().strip()
    admin = os.environ.get("MINIFLUX_ADMIN") or re.search(r"^MINIFLUX_ADMIN=(.*)$", (ROOT / ".env").read_text(), re.M).group(1).strip()
    state_file = ROOT / "secrets" / "feed_sync_state.json"
    state, lines = sync(call, admin_key, admin, load_state(state_file), lambda rows: run_sql(upsert_sql(rows)))
    save_state(state_file, state)
    print("\n".join(lines))
    if any(line.startswith("ERROR") for line in lines):
        print("next: journalctl -u miniflux-feed-sync -n 50")
        sys.exit(1)
    print("next: bash Docker/_global/scripts/post-update-check.sh Miniflux")


if __name__ == "__main__":
    main()
