#!/usr/bin/env bash
# Rebuild the Stonks image from the code repo and redeploy, preserving data.
#
#   Code repo (builds image):  ~/Documents/development/Stonks
#   Deploy dir (this folder):  ~/Projects/Docker/Stonks
#
# The SQLite DB (transactions, dividends, snapshots) lives in ./data and is a
# bind mount, so it survives container recreation. This script also backs it up
# to ./data/backups/ before each deploy, just in case.
set -euo pipefail

CODE_DIR="${STONKS_CODE_DIR:-$HOME/Documents/development/Stonks}"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="$DEPLOY_DIR/data/stonks.db"

echo "==> Backing up database (best-effort; the ./data bind mount preserves it regardless)"
ts="$(date +%Y%m%d-%H%M%S)"
cd "$DEPLOY_DIR"
# Run inside the container: it owns /data (root), so it can write /data/backups.
if docker compose exec -T stonks sh -c \
     "test -f /data/stonks.db && mkdir -p /data/backups && cp -p /data/stonks.db /data/backups/stonks-$ts.db && ls -1t /data/backups/stonks-*.db | tail -n +21 | xargs -r rm -f" 2>/dev/null; then
  echo "    saved data/backups/stonks-$ts.db"
else
  echo "    skipped (container not running or no DB yet) — data on disk is untouched"
fi

echo "==> Building stonks:latest from $CODE_DIR"
if [ ! -f "$CODE_DIR/Dockerfile" ]; then
  echo "ERROR: no Dockerfile at $CODE_DIR (set STONKS_CODE_DIR to the code repo)" >&2
  exit 1
fi
docker build -t stonks:latest "$CODE_DIR"

echo "==> Redeploying"
cd "$DEPLOY_DIR"
docker compose up -d

echo "==> Health check"
sleep 5
docker compose exec -T stonks python -c "import urllib.request as u; print(u.urlopen('http://localhost:8000/healthz').read().decode())"
echo "==> Done."
