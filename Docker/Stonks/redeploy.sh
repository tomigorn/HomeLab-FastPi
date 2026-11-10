#!/usr/bin/env bash
# Rebuild the Stonks image from the code repo (rust/) and redeploy, preserving data.
#
#   Code repo (builds image):  ~/Documents/development/Stonks/rust
#   Deploy dir (this folder):  ~/Projects/Docker/Stonks
#
# The SQLite DB lives in ./data (bind mount) and survives container recreation; a copy goes to
# ./data/backups/ before each deploy. The build (BoringSSL) is heavy: it takes the shared
# rust-build lock, two cargo jobs, and waits for 1.5 GB of free RAM.
set -euo pipefail

CODE_DIR="${STONKS_CODE_DIR:-$HOME/Documents/development/Stonks/rust}"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK="${RUST_BUILD_LOCK:-$HOME/.cache/claude-work/rust-build.lock}"

echo "==> Backing up database (best-effort; the ./data bind mount preserves it regardless)"
ts="$(date +%Y%m%d-%H%M%S)"
cd "$DEPLOY_DIR"
mkdir -p data/backups 2>/dev/null || true
if [ -f data/stonks.db ] && cp -p data/stonks.db "data/backups/stonks-$ts.db" 2>/dev/null; then
  ls -1t data/backups/stonks-*.db | tail -n +21 | xargs -r rm -f
  echo "    saved data/backups/stonks-$ts.db"
else
  echo "    skipped (no DB yet or not writable) — data on disk is untouched"
fi

echo "==> Building stonks:latest from $CODE_DIR"
[ -f "$CODE_DIR/Dockerfile" ] || { echo "ERROR: no Dockerfile at $CODE_DIR (set STONKS_CODE_DIR)" >&2; exit 1; }
mkdir -p "$(dirname "$LOCK")"
flock "$LOCK" bash -c '
  while [ "$(awk "/MemAvailable/{print \$2}" /proc/meminfo)" -lt 1500000 ]; do echo "    waiting for 1.5 GB free RAM"; sleep 30; done
  docker build --build-arg CARGO_BUILD_JOBS=2 -t stonks:latest "$0"' "$CODE_DIR"

echo "==> Redeploying"
docker compose up -d

echo "==> Health check"
for i in $(seq 1 10); do
  ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' stonks 2>/dev/null || true)
  if [ -n "$ip" ] && curl -sf -m 3 "http://$ip:8000/healthz"; then echo; echo "==> Done."; exit 0; fi
  sleep 2
done
echo "ERROR: /healthz did not answer; docker logs stonks" >&2
exit 1
