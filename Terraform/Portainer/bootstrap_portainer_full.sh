#!/usr/bin/env bash
set -euo pipefail

# Full bootstrap for Portainer: initialize admin, authenticate, create local Docker endpoint.
# Requires: curl, jq

HOST=${1:-localhost}
PORT=${2:-9000}
ADMIN_PASS=${3:-}

if [ -z "${ADMIN_PASS}" ]; then
  echo "Usage: $0 [host] [port] <admin-password>" >&2
  echo "Example: $0 localhost 9000 'S3cureP@ss'" >&2
  exit 2
fi

BASE_URL="http://${HOST}:${PORT}"

echo "Waiting for Portainer to come up at ${BASE_URL} ..."
for i in {1..30}; do
  if curl -sS "${BASE_URL}/api/status" >/dev/null 2>&1; then
    echo "Portainer API is reachable"
    break
  fi
  sleep 2
done

echo "Initializing admin user (if not already initialized)"
init_resp=$(curl -sS -o /dev/stderr -w "%{http_code}" -X POST "${BASE_URL}/api/users/admin/init" -H "Content-Type: application/json" -d "{ \"Username\": \"admin\", \"Password\": \"${ADMIN_PASS}\" }") || true
# If init fails with 409 or similar, continue

echo "Authenticating as admin to obtain JWT..."
auth=$(curl -sS -X POST "${BASE_URL}/api/auth" -H "Content-Type: application/json" -d "{ \"Username\": \"admin\", \"Password\": \"${ADMIN_PASS}\" }") || true
jwt=$(echo "$auth" | jq -r '.jwt // .JWT // empty') || true
if [ -z "$jwt" ]; then
  # Try HTTPS if HTTP auth failed
  echo "HTTP auth failed, trying HTTPS..."
  BASE_URL_HTTPS="https://${HOST}:9443"
  auth=$(curl -k -sS -X POST "${BASE_URL_HTTPS}/api/auth" -H "Content-Type: application/json" -d "{ \"Username\": \"admin\", \"Password\": \"${ADMIN_PASS}\" }") || true
  jwt=$(echo "$auth" | jq -r '.jwt // .JWT // empty') || true
fi

if [ -z "$jwt" ]; then
  echo "Failed to obtain JWT from Portainer auth response:" >&2
  echo "$auth" >&2
  exit 3
fi
echo "Obtained JWT token"

auth_header="Authorization: Bearer ${jwt}"

echo "Checking for existing endpoints..."
existing=$(curl -sS -H "$auth_header" "${BASE_URL}/api/endpoints")
exists=$(echo "$existing" | jq -r --arg NAME "local" '.[] | select(.Name==$NAME) | .Id' | head -n1 || true)
if [ -n "$exists" ]; then
  echo "Endpoint 'local' already exists with id: $exists"
  exit 0
fi

echo "Creating local Docker endpoint (unix socket)"
create_payload=$(jq -n --arg name "local" --arg url "unix:///var/run/docker.sock" '{ Name: $name, URL: $url, PublicURL: "", GroupID: 1, TLS: false }')
create_resp=$(curl -sS -X POST "${BASE_URL}/api/endpoints" -H "Content-Type: application/json" -H "$auth_header" -d "$create_payload")
echo "Created endpoint response: $create_resp"

echo "Bootstrap complete. You should now be able to login to Portainer (admin) and see the 'local' endpoint."
