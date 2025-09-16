#!/usr/bin/env python3
"""Create one-time invites in Authentik and list groups.

Usage examples:
  # list available groups
  AUTHENTIK_API_TOKEN=... AUTHENTIK_BASE_URL=http://auth.local:9000 python3 scripts/create_invite.py --list-groups

  # create a one-time invite for group by name
  AUTHENTIK_API_TOKEN=... AUTHENTIK_BASE_URL=http://auth.local:9000 python3 scripts/create_invite.py --group "media-users" --uses 1 --minutes 1440

The script will try common Authentik API endpoints to list groups. If it cannot resolve a group by name
you can pass a numeric group id instead.
"""

import os
import sys
import argparse
import requests
from datetime import datetime, timedelta
from urllib.parse import urljoin


API_TOKEN = os.environ.get("AUTHENTIK_API_TOKEN")
BASE = os.environ.get("AUTHENTIK_BASE_URL", "http://localhost:9000").rstrip("/")

if not API_TOKEN:
    print("Error: set the AUTHENTIK_API_TOKEN environment variable (create one in authentik admin).")
    sys.exit(1)

HEADERS = {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}


def try_get(url, params=None):
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
    except requests.RequestException:
        pass
    return None


def list_groups():
    # Try a small list of likely endpoints used by different authentik versions
    endpoints = [
        "/api/v3/identity/groups/",
        "/api/v3/identities/groups/",
        "/api/v3/groups/",
        "/api/v3/identity/group/",
        "/api/v3/identities/group/",
    ]
    for ep in endpoints:
        url = BASE + ep
        data = try_get(url)
        if not data:
            continue
        # Many list endpoints return a paginated object with 'results'
        items = data.get("results") if isinstance(data, dict) and "results" in data else data
        out = []
        for it in items:
            gid = it.get("id") or it.get("pk")
            name = it.get("name") or it.get("slug") or it.get("display_name")
            slug = it.get("slug")
            out.append({"id": gid, "name": name, "slug": slug})
        if out:
            print(f"Groups from {url}:")
            for g in out:
                print(f"  id={g['id']}  name={g['name']}  slug={g['slug']}")
            return out
    print("Could not list groups automatically. Please create groups in the Authentik UI and pass their numeric IDs or slugs.")
    return None


def resolve_group_ids(requested_groups):
    # requested_groups: list of group names or numeric ids (strings)
    resolved = []
    # First, try to fetch groups once
    endpoints = [
        "/api/v3/identity/groups/",
        "/api/v3/identities/groups/",
        "/api/v3/groups/",
    ]
    groups = []
    for ep in endpoints:
        url = BASE + ep
        data = try_get(url)
        if not data:
            continue
        items = data.get("results") if isinstance(data, dict) and "results" in data else data
        for it in items:
            groups.append(it)
        if groups:
            break

    for rg in requested_groups:
        rg = rg.strip()
        if rg.isdigit():
            resolved.append(int(rg))
            continue
        # try to match by name or slug
        found = None
        for g in groups:
            if str(g.get("id")) == rg:
                found = g
                break
            if g.get("name") and g.get("name") == rg:
                found = g
                break
            if g.get("slug") and g.get("slug") == rg:
                found = g
                break
        if found:
            resolved.append(found.get("id"))
        else:
            print(f"Warning: could not resolve group '{rg}' by name/slug. Please pass numeric id instead.")
    return resolved


def create_invite(group_ids, uses=1, minutes=60, name="invite"):
    url = BASE + "/api/v3/invites/invite/"
    expires = (datetime.utcnow() + timedelta(minutes=minutes)).isoformat() + "Z"
    payload = {
        "name": name,
        "uses": uses,
        "valid_until": expires,
    }
    if group_ids:
        payload["target_groups"] = group_ids
    r = requests.post(url, json=payload, headers=HEADERS, timeout=10)
    if r.status_code not in (200, 201):
        print("Failed to create invite:", r.status_code, r.text)
        return None
    data = r.json()
    # Try common fields for the token/slug
    token = data.get("slug") or data.get("token") or data.get("id")
    if token:
        link = BASE + "/if/" + str(token)
    else:
        link = None
    print("Invite created. Raw response:")
    print(data)
    if link:
        print("Invite link:", link)
    else:
        print("No slug/token found in response; inspect JSON above for the invite identifier.")
    return data


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--list-groups", action="store_true", help="List groups available in Authentik")
    p.add_argument("--group", action="append", help="Group name, slug or id to assign to the invite (can be repeated)")
    p.add_argument("--uses", type=int, default=1, help="Number of uses for the invite")
    p.add_argument("--minutes", type=int, default=60, help="Expiry time in minutes")
    p.add_argument("--name", default="invite", help="Invite name")
    args = p.parse_args()

    if args.list_groups:
        list_groups()
        return

    if not args.group:
        print("Error: pass at least one --group NAME_OR_ID or run with --list-groups to see available groups.")
        sys.exit(2)

    group_ids = resolve_group_ids(args.group)
    if not group_ids:
        print("Error: no valid group ids resolved. Aborting.")
        sys.exit(3)

    create_invite(group_ids, uses=args.uses, minutes=args.minutes, name=args.name)


if __name__ == "__main__":
    main()