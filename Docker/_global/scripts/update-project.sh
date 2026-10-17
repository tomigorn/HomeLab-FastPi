#!/usr/bin/env bash
# update-project.sh <compose-dir> <mode> [backup-paths...]
#   mode: pull | build | recreate
# Follows _global/UPDATE-RUNBOOK.md: snapshot image IDs, back up stateful paths
# (bind dirs or "vol:<name>"), update, wait, verify every container of the
# project is running (and healthy if it has a healthcheck) with no crash loop;
# on failure re-tag the old images and recreate (automatic rollback).
set -uo pipefail
dir=$1; mode=$2; shift 2
cd "$dir" || { echo "FAIL $dir: no such dir"; exit 2; }
proj=$(docker compose config --format json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')
bk="$HOME/backups/pre-update/$(date +%F)/$proj"; mkdir -p "$bk"
echo "=== $proj ($dir) mode=$mode"

# snapshot: container -> image ref + running image id
declare -A oldid
while read -r name ref; do oldid[$name]="$ref|$(docker inspect -f '{{.Image}}' "$name")"; done < <(docker compose ps -q | xargs -r docker inspect -f '{{.Name}} {{.Config.Image}}' | sed 's|^/||')
for n in "${!oldid[@]}"; do echo "  before: $n ${oldid[$n]}"; done

# backups
for b in "$@"; do
  if [[ $b == vol:* ]]; then v=${b#vol:}; docker run --rm -v "$v":/from:ro -v "$bk":/to alpine tar czf "/to/vol-$v.tgz" -C /from . && echo "  backup: volume $v -> $bk"
  else [[ -e $b ]] && sudo tar czf "$bk/$(basename "$b").tgz" -C "$(dirname "$b")" "$(basename "$b")" && echo "  backup: $b -> $bk"; fi
done

case $mode in
  pull)     docker compose pull -q ${SERVICES:-} 2>&1 | grep -viE 'pulling|pulled|^$' | head -5 ;;
  build)    docker compose build --pull -q ${SERVICES:-} 2>&1 | grep -viE '^\s*$' | tail -3 ;;
  recreate) : ;;
esac
docker compose up -d --remove-orphans 2>&1 | grep -E 'Recreat|Creat|Error|error' | head -8

sleep "${WAIT:-45}"
ok=1
for n in "${!oldid[@]}"; do
  st=$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}nohc{{end}} {{.RestartCount}}' "$n" 2>/dev/null || echo "missing")
  new=$(docker inspect -f '{{.Image}}' "$n" 2>/dev/null)
  echo "  after : $n $st  image $( [[ "$new" == "${oldid[$n]#*|}" ]] && echo unchanged || echo UPDATED)"
  [[ $st == running\ nohc\ 0 || $st == running\ healthy\ 0 || $st == running\ starting\ 0 ]] || ok=0
done
if (( ok )); then echo "OK $proj"; exit 0; fi

echo "ROLLBACK $proj"
for n in "${!oldid[@]}"; do ref=${oldid[$n]%%|*}; id=${oldid[$n]#*|}; docker tag "$id" "$ref"; done
docker compose up -d --force-recreate 2>&1 | tail -3; sleep 20
docker compose ps --format '{{.Name}} {{.Status}}'
exit 1
