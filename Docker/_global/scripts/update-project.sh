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

# snapshot: container -> "ref|imageid|containerid|restartcount". The container id
# and RestartCount are the baseline: RestartCount is a LIFETIME counter, so the
# verify must compare the DELTA during this update, not demand it be 0 - a project
# member that restarted once days ago and is NOT recreated here would otherwise
# trip a false rollback.
declare -A oldid
while read -r name ref id rc; do oldid[$name]="$ref|$(docker inspect -f '{{.Image}}' "$name")|$id|$rc"; done < <(docker compose ps -q | xargs -r docker inspect -f '{{.Name}} {{.Config.Image}} {{.Id}} {{.RestartCount}}' | sed 's|^/||')
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
  IFS='|' read -r _ oldimg oldcid oldrc <<< "${oldid[$n]}"
  info=$(docker inspect -f '{{.State.Status}}|{{if index .State "Health"}}{{(index .State "Health").Status}}{{else}}nohc{{end}}|{{.Image}}|{{.Id}}|{{.RestartCount}}' "$n" 2>/dev/null || echo "missing|-|-|-|0")
  IFS='|' read -r status health newimg newcid newrc <<< "$info"
  # A recreated container is a NEW container (id changed) whose count starts at 0;
  # an untouched one keeps its old id and lifetime count. A crash loop shows up as
  # restarts DURING this window: >=2 on a fresh container, or any rise on an
  # untouched one.
  if [[ "$newcid" == "$oldcid" ]]; then crashloop=$(( newrc > oldrc )); else crashloop=$(( newrc >= 2 )); fi
  upd=$( [[ "$newimg" == "$oldimg" ]] && echo unchanged || echo UPDATED )
  echo "  after : $n $status $health rc=$oldrc->$newrc  image $upd"
  [[ $status == running && ( $health == healthy || $health == nohc || $health == starting ) && $crashloop -eq 0 ]] || ok=0
done
if (( ok )); then echo "OK $proj"; exit 0; fi

echo "ROLLBACK $proj"
for n in "${!oldid[@]}"; do IFS='|' read -r ref iid _ _ <<< "${oldid[$n]}"; docker tag "$iid" "$ref" 2>/dev/null; done
docker compose up -d --force-recreate 2>&1 | tail -3; sleep 20
docker compose ps --format '{{.Name}} {{.Status}}'
exit 1
