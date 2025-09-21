#!/usr/bin/env bash
set -euo pipefail

#!/usr/bin/env bash
set -euo pipefail

# create_agent_endpoint.sh <host> <name> <admin-pass> <enable-flag> <agent-port>
# If enable-flag is not "true", the script exits without doing anything.

HOST=${1:-}
NAME=${2:-}
ADMIN_PASS=${3:-}
ENABLE=${4:-false}
AGENT_PORT=${5:-9001}

if [ "${ENABLE}" != "true" ]; then
  echo "Agent creation not enabled; exiting"
  exit 0
fi

if [ -z "${HOST}" ] || [ -z "${NAME}" ] || [ -z "${ADMIN_PASS}" ]; then
  echo "Usage: $0 <host> <name> <admin-pass> <enable-flag> [agent-port]" >&2
  exit 2
fi

BASE_URL_HTTP="http://localhost:9000"
BASE_URL_HTTPS="https://localhost:9443"

echo "Waiting for Portainer API to become reachable..."
for i in {1..60}; do
  if curl -sS "${BASE_URL_HTTP}/api/status" >/dev/null 2>&1; then
    BASE_URL=${BASE_URL_HTTP}
    echo "Using HTTP API at ${BASE_URL}"
    break
  fi
  if curl -k -sS "${BASE_URL_HTTPS}/api/status" >/dev/null 2>&1; then
    BASE_URL=${BASE_URL_HTTPS}
    echo "Using HTTPS API at ${BASE_URL}"
    break
  fi
  sleep 2
done

if [ -z "${BASE_URL}" ]; then
  echo "Portainer API not reachable after timeout" >&2
  exit 3
fi

echo "Authenticating to Portainer (will retry until successful)..."
auth=""
jwt=""
for i in {1..30}; do
  auth=$(curl -sS -X POST "${BASE_URL}/api/auth" -H "Content-Type: application/json" -d "{ \"Username\": \"admin\", \"Password\": \"${ADMIN_PASS}\" }") || true
  jwt=$(echo "$auth" | jq -r '.jwt // .JWT // empty') || true
  if [ -n "$jwt" ] && [ "$jwt" != "null" ]; then
    echo "Authenticated to Portainer"
    break
  fi
  echo "Auth attempt $i failed, retrying..."
  sleep 2
done

if [ -z "$jwt" ]; then
  echo "Failed to authenticate to Portainer after retries:" >&2
  echo "$auth" >&2
  exit 4
fi

auth_header="Authorization: Bearer ${jwt}"

echo "Checking if endpoint '${NAME}' already exists..."
existing=$(curl -sS -H "$auth_header" "${BASE_URL}/api/endpoints")
exists=$(echo "$existing" | jq -r --arg NAME "$NAME" '.[] | select(.Name==$NAME) | .Id' | head -n1 || true)
if [ -n "$exists" ]; then
  echo "Endpoint '$NAME' already exists with id: $exists"
  exit 0
fi
URL="tcp://${HOST}:${AGENT_PORT}"
echo "Creating agent endpoint '$NAME' with URL $URL"
payload=$(jq -n --arg name "$NAME" --arg url "$URL" '{ Name: $name, URL: $url, PublicURL: "", GroupID: 1, TLS: false }')
resp=$(curl -sS -X POST "${BASE_URL}/api/endpoints" -H "Content-Type: application/json" -H "$auth_header" -d "$payload")
echo "Create response: $resp"
echo "Done."
