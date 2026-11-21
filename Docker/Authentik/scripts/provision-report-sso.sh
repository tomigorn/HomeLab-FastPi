#!/usr/bin/env bash
# Runs provision-report-sso.py (Authentik app `report`, forward auth, groups streaming-users + streaming-admins). Idempotent; prints only the OK line.
# Usage: provision-report-sso.sh [--rollback]
set -euo pipefail
cd /home/pi/Projects/Docker/Authentik
case "${1:-}" in
  "") rb=0 ;;
  --rollback) rb=1 ;;
  -h|--help) sed -n 2,3p "$0"; exit 0 ;;
  *) echo "usage: $0 [--rollback]" >&2; exit 2 ;;
esac
out=$(sudo docker compose exec -T -e ROLLBACK=$rb server ak shell < scripts/provision-report-sso.py 2>/dev/null)
grep '^OK ' <<<"$out" || { echo "provisioning failed (no OK line)" >&2; exit 1; }
echo "next: bash scripts/canary-verify.sh"
