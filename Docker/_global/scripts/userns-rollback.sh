#!/usr/bin/env bash
set -euo pipefail

# Returns dockerd to the original (untouched) data-root after a Phase 1 userns-remap cutover.
# The cutover COPIES volumes into the new root and never touches the original, so removing the
# remap and restarting docker makes every original volume/image/container reappear as it was.

DOCKER_DIR=/home/pi/Projects/Docker
MANIFEST=${MANIFEST:-/home/pi/Projects/Docker/_global/docs/userns-remap-snapshot/touched-files.manifest}
ts(){ date -Is; }

panic() {
  echo "[$(ts)] PANIC rollback: removing remap, restarting docker"
  sudo rm -f /etc/docker/daemon.json
  sudo systemctl restart docker
  sleep 3
  if docker info 2>/dev/null | grep -qi 'userns'; then
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
