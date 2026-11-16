#!/usr/bin/env python3
"""Idempotent Miniflux subscriptions from feeds.toml: creates missing categories and feeds, moves listed feeds to their category.

Usage: Docker/Miniflux/scripts/subscribe.py [--dry-run] [--prune] [-h|--help]
  --prune    also unsubscribe the admin's feeds that feeds.toml no longer lists, and remove categories that end up empty (sync_users.py follows for the other users)
Talks to the API on 127.0.0.1:8097 with secrets/api_key; a {feed_key} placeholder in a URL comes from secrets/feed_key when that file exists.
"""
import json
import pathlib
import re
import sys
import tomllib
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "http://127.0.0.1:8097/v1"
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def load_feeds(text, secrets):
    data = tomllib.loads(text)
    feeds = set()
    for f in data.get("feed", []):
        feeds.add((f["category"], f["url"].format(**secrets) if "{" in f["url"] else f["url"]))
    for g in data.get("github", []):
        kind = g.get("kind", "releases")
        for repo in g["repos"]:
            if not REPO.match(repo):
                raise ValueError(f"not owner/repo: {repo!r}")
            feeds.add((g["category"], f"https://github.com/{repo}/{kind}.atom"))
    return sorted(feeds)


def plan(existing, wanted):
    """existing: url -> (feed id, category title). Returns (to create, (feed id, category) to move)."""
    create, move = [], []
    for category, url in wanted:
        if url not in existing:
            create.append((category, url))
        elif existing[url][1] != category:
            move.append((existing[url][0], category))
    return create, move


def prune(existing, wanted):
    """Feeds not listed: [(feed id, url)] to delete, and the categories that lose their last feed and are not listed."""
    urls = {u for _, u in wanted}
    gone = sorted((fid, url) for url, (fid, _) in existing.items() if url not in urls)
    left = {cat for url, (_, cat) in existing.items() if url in urls} | {c for c, _ in wanted}
    cats = sorted({existing[url][1] for _, url in gone} - left)
    return gone, cats


def read_secrets(secrets_dir):
    path = secrets_dir / "feed_key"
    return {"feed_key": path.read_text().strip()} if path.exists() else {}


def masked(url):
    return re.sub(r"(X-FEED-KEY=)[^&\s\"']+", r"\1***", url)


def call(method, path, key, body=None, timeout=60):
    req = urllib.request.Request(API + path, method=method, headers={"X-Auth-Token": key, "Content-Type": "application/json"},
                                 data=None if body is None else json.dumps(body).encode())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def main():
    args = sys.argv[1:]
    if {"-h", "--help"} & set(args) or set(args) - {"--dry-run", "--prune"}:
        print(__doc__.strip())
        sys.exit(0 if {"-h", "--help"} & set(args) else 2)
    dry = "--dry-run" in args
    key = (ROOT / "secrets" / "api_key").read_text().strip()
    secrets = read_secrets(ROOT / "secrets")
    wanted = load_feeds((ROOT / "feeds.toml").read_text(), secrets)
    cats = {c["title"]: c["id"] for c in call("GET", "/categories", key)}
    feeds = call("GET", "/feeds", key)
    existing = {f["feed_url"]: (f["id"], f["category"]["title"]) for f in feeds}
    create, move = plan(existing, wanted)
    for title in sorted({c for c, _ in create} | {c for _, c in move}) if not dry else []:
        if title not in cats:
            cats[title] = call("POST", "/categories", key, {"title": title})["id"]
    for category, url in create:
        print(f"subscribe {category}: {masked(url)}")
        if not dry:
            try:
                call("POST", "/feeds", key, {"feed_url": url, "category_id": cats[category]})
            except urllib.error.HTTPError as e:
                print(f"  FAILED {e.code}: {masked(e.read().decode())[:200]}")
    for feed_id, category in move:
        print(f"move feed {feed_id} -> {category}")
        if not dry:
            call("PUT", f"/feeds/{feed_id}", key, {"category_id": cats[category]})
    gone, empty = prune(existing, wanted) if "--prune" in args else ([], [])
    for feed_id, url in gone:
        print(f"unsubscribe {masked(url)}")
        if not dry:
            call("DELETE", f"/feeds/{feed_id}", key)
    for title in empty:
        print(f"remove category {title}")
        if not dry:
            call("DELETE", f"/categories/{cats[title]}", key)
    print(f"OK {len(wanted)} listed, {len(create)} new, {len(move)} moved, {len(gone)} removed" + (" (dry run)" if dry else ""))
    print("next: bash Docker/_global/scripts/post-update-check.sh Miniflux")


if __name__ == "__main__":
    main()
