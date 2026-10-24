#!/usr/bin/env bash
# Authentik caches each user's app list for 24 h and clears it only when a user, group, app or policy is saved, not when a group's members change.
# This clears the cached app lists (nothing else) whenever group memberships or the group hierarchy change. Run by authentik-app-cache.timer every minute.
#   app-cache-on-group-change.sh          check and clear if changed
#   app-cache-on-group-change.sh --force  clear now
set -euo pipefail
cd /home/pi/Projects/Docker/Authentik
STATE=${STATE:-$HOME/.local/state/authentik-app-cache/memberships.md5}
mkdir -p "$(dirname "$STATE")"

sql() { docker compose exec -T postgresql sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "$1"' sh "$1"; }

now=$(sql "select md5(coalesce((select string_agg(user_id || ':' || group_id, ',' order by user_id, group_id) from authentik_core_user_groups), '') || '|' || coalesce((select string_agg(child_id || '<' || parent_id, ',' order by child_id, parent_id) from authentik_core_groupparentage), ''))")
[[ $now =~ ^[0-9a-f]{32}$ ]] || { echo "no fingerprint: $now" >&2; exit 1; }
before=$(cat "$STATE" 2>/dev/null || true)

if [[ ${1:-} == --force || $now != "$before" ]]; then
  n=$(sql "with d as (delete from django_postgres_cache_cacheentry where cache_key like '%:goauthentik.io/policies/app_access/%' returning 1) select count(*) from d")
  echo "memberships $([[ -n $before ]] && echo changed || echo "first run"): cleared $n cached app lists"
fi
printf '%s\n' "$now" > "$STATE"
