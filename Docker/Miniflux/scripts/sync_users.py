#!/usr/bin/env python3
"""Gives every non-admin Miniflux user the feeds and categories of MINIFLUX_ADMIN and keeps them in sync (idempotent).

Usage: Docker/Miniflux/scripts/sync_users.py [-h|--help]
Adds what the admin has, moves synced feeds to the admin's category, removes synced feeds and empty synced categories the admin dropped.
A user's copy of an admin feed fetched more than a minute before the admin's is refreshed, so changed titles and status blocks reach every user within one run.
A user's own feeds and categories are never touched; integrations (Telegram) are never copied.
Every user (admin included) gets a "Tech stack" link in the header menu (custom JavaScript between LINK_START and LINK_END) and status pills instead of the leading status mark of the CVE titles (custom CSS and JavaScript between PILL_*_START and PILL_*_END); the user's own custom CSS and JavaScript stay after these blocks.
Each user is reached with its own API key "feed-sync" (derived from secrets/api_key, row upserted over psql when missing).
State (which feeds came from the sync): secrets/feed_sync_state.json. Runs every 5 minutes by miniflux-feed-sync.timer.
"""
import datetime
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
LAG = datetime.timedelta(minutes=1)
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
MARKS = [  # title mark of vl-severity-feed, pill class, pill label (none: row muted), tooltip
    ("❗", "action", "Action needed", "Our version is affected: action needed"),
    ("❔", "check", "Check version", "We run it, version unclear: check by hand"),
    ("✅", "ok", "Not affected", "We run it, our version is not affected"),
    ("ℹ️", "notours", "", "Not our product"),
]
PILL_CSS_START, PILL_CSS_END = "/* homelab-status-pills */", "/* /homelab-status-pills */"
PILL_JS_START, PILL_JS_END = PILL_CSS_START, PILL_CSS_END
PILL_CSS = PILL_CSS_START + """
html:not(.vl-pills) :is(.item-title, .entry-header h1) { visibility: hidden; animation: vl-reveal 0s 0.8s forwards; }
@keyframes vl-reveal { to { visibility: visible; } }
.vl-pill { display: inline-block; margin-right: 0.5em; padding: 0.15em 0.6em; border: 1px solid transparent; border-radius: 1em; font: 600 0.7em/1.3 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; letter-spacing: 0.02em; vertical-align: 0.12em; white-space: nowrap; }
.entry-header .vl-pill { font-size: 0.45em; vertical-align: 0.35em; }
.vl-pill.vl-action { background: #cf222e; border-color: #cf222e; color: #fff; font-weight: 700; }
.vl-pill.vl-check { background: color-mix(in srgb, #d4a72c 18%, transparent); border-color: color-mix(in srgb, #d4a72c 55%, transparent); color: color-mix(in srgb, #9a6700 70%, var(--body-color)); }
.vl-pill.vl-ok { border-color: color-mix(in srgb, #2da44e 45%, transparent); color: color-mix(in srgb, #2da44e 60%, var(--body-color)); font-weight: 500; }
article.vl-notours .item-title a, .entry-header.vl-notours h1 a { color: var(--item-status-read-title-link-color); font-weight: normal; }
""" + PILL_CSS_END
PILL_JS = PILL_JS_START + """
(() => {
  const marks = new Map(Object.entries(""" + json.dumps({m: [c, l, t] for m, c, l, t in MARKS}, ensure_ascii=False) + """).map(([k, v]) => [k.replace(/\\uFE0F/g, ""), v]));
  for (const a of document.querySelectorAll(".item-title a, .entry-header h1 a")) {
    const text = a.firstChild;
    const m = text && text.nodeType === 3 && text.data.match(/^\\s*(\\S)\\uFE0F?\\s+/u);
    const hit = m && marks.get(m[1]);
    if (!hit) continue;
    const [cls, label, tip] = hit;
    text.data = text.data.slice(m[0].length);
    a.closest("article, .entry-header")?.classList.add("vl-" + cls);
    if (!label) { a.title = tip; continue; }
    const pill = document.createElement("span");
    pill.className = "vl-pill vl-" + cls;
    pill.textContent = label;
    pill.title = tip;
    a.prepend(pill);
  }
  document.documentElement.classList.add("vl-pills");
})();
""" + PILL_JS_END


MANAGED = re.compile(r"/\* (homelab-[a-z-]+) \*/.*?/\* /\1 \*/\n?", re.S)


def with_blocks(text, blocks):
    """The managed blocks first, in this order, then the user's own text; every older homelab-* block is dropped."""
    own = MANAGED.sub("", text or "").strip()
    return "\n".join(blocks) + ("\n" + own if own else "")


def managed_settings(user):
    """The custom_js and stylesheet fields that differ from what the user should have."""
    want = {"custom_js": with_blocks(user.get("custom_js"), [LINK_JS, PILL_JS]),
            "stylesheet": with_blocks(user.get("stylesheet"), [PILL_CSS])}
    return {k: v for k, v in want.items() if v != user.get(k)}


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


def checked(feed):
    try:
        return datetime.datetime.fromisoformat(feed.get("checked_at") or "")
    except ValueError:
        return None


def sync_user(call, key, name, admin_feeds, admin_cats, synced, lines, admin_checked=None):
    feeds_synced, cats_synced = set(synced.get("feeds", [])), set(synced.get("categories", []))
    cats = {c["title"]: c["id"] for c in call("GET", "/categories", key)}
    listed = call("GET", "/feeds", key)
    feeds = {f["feed_url"]: (f["id"], f["category"]["title"]) for f in listed}
    added = moved = removed = 0
    for f in listed:
        theirs, ours = checked(f), (admin_checked or {}).get(f["feed_url"])
        if theirs and ours and ours - theirs > LAG:
            lines.append(f"{name}: refresh {masked(f['feed_url'])}")
            try:
                call("PUT", f"/feeds/{f['id']}/refresh", key, timeout=TIMEOUT)
            except urllib.error.HTTPError as e:
                lines.append(f"  FAILED {e.code}: {error_text(e)}")
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
    admin_list = call("GET", "/feeds", admin_key)
    admin_feeds = {f["feed_url"]: f["category"]["title"] for f in admin_list}
    admin_checked = {f["feed_url"]: checked(f) for f in admin_list}
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
            new_state[uid] = sync_user(call, user_key(admin_key, u["id"]), u["username"], admin_feeds, admin_cats, state.get(uid, {}), lines, admin_checked)
        except urllib.error.HTTPError as e:
            lines.append(f"ERROR {u['username']}: {e.code} {error_text(e)}")
            if uid in state:
                new_state[uid] = state[uid]
    if not users:
        lines.append("no other users")
    for u in everyone:
        changed = managed_settings(u)
        if changed:
            call("PUT", f"/users/{u['id']}", admin_key, changed)
            lines.append(f"{u['username']}: header link and status pills")
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
