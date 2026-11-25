#!/usr/bin/env bash
set -euo pipefail

# Returns dockerd to the original (untouched) data-root after a Phase 1 userns-remap cutover.
# The cutover COPIES volumes into the new root and never touches the original, so removing the
# remap and restarting docker makes every original volume/image/container reappear as it was.

DOCKER_DIR=/home/pi/Projects/Docker
MANIFEST=${MANIFEST:-/home/pi/Projects/Docker/_global/docs/userns-remap-snapshot/touched-files.manifest}
DAEMON_JSON=${DAEMON_JSON:-/etc/docker/daemon.json}
ts(){ date -Is; }

# drop only the userns-remap key: dns, log rotation and live-restore stay; the original is kept as daemon.json.bak-<time>
remove_remap() {
  [ -e "$DAEMON_JSON" ] || { echo "[$(ts)] no $DAEMON_JSON, nothing to remove"; return 0; }
  local cur new
  cur=$(sudo cat "$DAEMON_JSON") && jq -e . >/dev/null <<<"$cur" || { echo "[$(ts)] $DAEMON_JSON is not valid JSON: fix it by hand, docker NOT restarted"; return 1; }
  if ! jq -e 'has("userns-remap")' >/dev/null <<<"$cur"; then echo "[$(ts)] no userns-remap key in $DAEMON_JSON, file left as it is"; return 0; fi
  new=$(jq 'del(."userns-remap")' <<<"$cur")
  sudo cp -p "$DAEMON_JSON" "$DAEMON_JSON.bak-$(date +%Y%m%d-%H%M%S)"
  printf '%s\n' "$new" | sudo tee "$DAEMON_JSON.new" >/dev/null && sudo mv "$DAEMON_JSON.new" "$DAEMON_JSON"
  echo "[$(ts)] userns-remap removed from $DAEMON_JSON (rest kept)"
}

panic() {
  echo "[$(ts)] PANIC rollback: removing remap, restarting docker"
  remove_remap
  sudo systemctl restart docker
  sleep "${RESTART_WAIT:-3}"
  local secopts
  secopts=$(docker info --format '{{.SecurityOptions}}' 2>/dev/null || true)
  if grep -qi 'userns' <<<"$secopts"; then
    echo "[$(ts)] WARNING: docker info still reports userns — inspect manually"
  else
    echo "[$(ts)] remap OFF; original data-root active"
  fi
  docker ps --format '{{.Names}}' | wc -l | xargs echo "[$(ts)] containers running:"
}

full() {
  panic
  echo "[$(ts)] reverting compose userns_mode:host edits from manifest"
  if [ -f "$MANIFEST" ]; then
    cd "$DOCKER_DIR"
    while IFS= read -r f; do
      [ -n "$f" ] && git checkout -- "$f" && echo "  reverted $f"
    done < "$MANIFEST"
  else
    echo "[$(ts)] no manifest at $MANIFEST — revert compose edits by hand (git status)"
  fi
  echo "[$(ts)] reverting Phase 1 chowns"
  sudo chown 0:0 "$DOCKER_DIR/Stonks/data" 2>/dev/null || true
  sudo chown -R 1000:1000 "$DOCKER_DIR/Claude-Mockups/answers" 2>/dev/null || true
  echo "[$(ts)] done. Bring stacks up in Gate A->D order and run the verification checklist."
}

case "${1:-}" in
  panic) panic ;;
  full)  full ;;
  *) echo "usage: $0 {panic|full}"; echo "  panic = remove remap + restart docker (fastest, original root back)"; echo "  full  = panic + git-revert compose edits + revert chowns"; exit 2 ;;
esac
