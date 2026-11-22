#!/usr/bin/env bash
# Restores the look fields of the `report` tile (name, icon, description, section) from a backup JSON; the app, provider and bindings stay.
# Usage: restore-report-tile.sh [backup.json]   (default /home/pi/.cache/claude-work/report-tile/backup-report-app.json)
set -euo pipefail
case "${1:-}" in -h|--help) sed -n 2,3p "$0"; exit 0 ;; esac
f=${1:-/home/pi/.cache/claude-work/report-tile/backup-report-app.json}
[ -r "$f" ] || { echo "no backup file: $f" >&2; exit 1; }
cd /home/pi/Projects/Docker/Authentik
out=$(sudo docker compose exec -T -e "BACKUP=$(cat "$f")" server ak shell <<'PY' 2>/dev/null
import json, os
from authentik.core.models import Application
b = json.loads(os.environ["BACKUP"])
n = Application.objects.filter(slug=b["slug"]).update(name=b["name"], meta_icon=b["meta_icon"], meta_description=b["meta_description"], group=b["group"])
from django.core.cache import cache
from authentik.core.api.applications import user_app_cache_key
cache.delete_many(cache.keys(user_app_cache_key("*")) or [])
print(f"OK restored {b['slug']}: {n} app")
PY
)
grep '^OK ' <<<"$out" || { echo "restore failed" >&2; exit 1; }
