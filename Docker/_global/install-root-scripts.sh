#!/usr/bin/env bash
# Install root-owned copies of the scripts that root units run, so code pi can write never runs as root. Idempotent; re-run after editing one of them.
# Usage: install-root-scripts.sh          install / update the copies
#        install-root-scripts.sh --check  print the number of copies that differ from the repo or are not root-owned 0644 (0 = fine)
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
DEST=${ROOT_SCRIPTS_DEST:-/usr/local/libexec/fastpi}
SCRIPTS=(
  Docker/grafana/container-exporter/container_exporter.py
  Docker/grafana/smart-exporter/smart_exporter.py
  Server/4-Security-Monitoring/security_scan.py
)
if [[ ${1:-} == --check ]]; then
  n=0
  [[ $(stat -c '%U:%G %a' "$DEST" 2>/dev/null) == "root:root 755" ]] || n=$((n+1))
  for s in "${SCRIPTS[@]}"; do
    d="$DEST/${s##*/}"
    if ! cmp -s "$REPO/$s" "$d" || [[ $(stat -c '%U:%G %a' "$d") != "root:root 644" ]]; then n=$((n+1)); fi
  done
  echo "$n"; exit 0
fi
sudo install -d -o root -g root -m 0755 "$DEST"
for s in "${SCRIPTS[@]}"; do sudo install -o root -g root -m 0644 "$REPO/$s" "$DEST/"; done
echo "installed ${#SCRIPTS[@]} scripts to $DEST, drift: $("$0" --check)"
