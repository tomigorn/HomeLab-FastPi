#!/usr/bin/env bash
# Bootstrap script for Portainer initial admin creation
# This script demonstrates how to call Portainer's API to initialize the admin user.
# Review before running. Requires `jq` and `curl`.

set -euo pipefail

PORT=9000
HOST=localhost
ADMIN_PASS=${1:-}

if [ -z "${ADMIN_PASS}" ]; then
  echo "Usage: $0 <admin-password>" >&2
  exit 2
fi

echo "Checking Portainer status..."
curl -sS "http://${HOST}:${PORT}/api/status" | jq .

echo "Initializing admin user..."
curl -sS -X POST "http://${HOST}:${PORT}/api/users/admin/init" \
  -H "Content-Type: application/json" \
  -d "{ \"Password\": \"${ADMIN_PASS}\" }"

echo "Done. You should be able to login to Portainer with the provided password."
