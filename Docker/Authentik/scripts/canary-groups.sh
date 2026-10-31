#!/usr/bin/env bash
# Add/remove/list groups of the SSO test canary only, from a fixed allow-list. Usage: canary-groups.sh add|remove|list [group...]
set -euo pipefail
cd /home/pi/Projects/Docker/Authentik
ALLOWED="streaming-requesters"
action="${1:-list}"; shift || true
for g in "$@"; do
  case " $ALLOWED " in *" $g "*) ;; *) echo "group not allowed: $g" >&2; exit 2;; esac
done
case "$action" in add|remove|list) ;; *) echo "usage: $0 add|remove|list [group...]" >&2; exit 2;; esac
sudo docker compose exec -T -e ACTION="$action" -e GROUPS_ARG="$*" server ak shell <<'PY' 2>/dev/null
import os
from authentik.core.models import User, Group
u = User.objects.get(username="canary-test")
act = os.environ["ACTION"]
for n in os.environ["GROUPS_ARG"].split():
    g = Group.objects.get(name=n)
    if act == "add": u.groups.add(g)
    elif act == "remove": u.groups.remove(g)
print("CANARY_GROUPS active=%s groups=%s" % (u.is_active, sorted(x.name for x in u.groups.all())))
PY
