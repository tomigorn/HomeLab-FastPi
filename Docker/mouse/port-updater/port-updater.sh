#!/bin/sh
set -e

GLUETUN_IP="${GLUETUN_IP:-172.32.0.2}"

# --- Helper functions ---

wait_for_gluetun() {
  echo "Waiting for gluetun to become healthy..."
  i=0
  while [ $i -lt 60 ]; do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' gluetun_mouse 2>/dev/null)
    if [ "$STATUS" = "healthy" ]; then
      echo "Gluetun is healthy."
      return 0
    fi
    i=$((i + 1))
    sleep 5
  done
  echo "WARNING: Gluetun did not become healthy within 5 minutes."
  return 1
}

wait_for_qbittorrent() {
  echo "Waiting for qBittorrent web UI..."
  i=0
  while [ $i -lt 24 ]; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" http://${GLUETUN_IP}:8080 2>/dev/null)
    if [ "$CODE" = "200" ] || [ "$CODE" = "302" ]; then
      echo "qBittorrent is ready."
      return 0
    fi
    i=$((i + 1))
    sleep 5
  done
  echo "WARNING: qBittorrent did not become ready within 2 minutes."
  return 1
}

# Check quick HTTP reachability to qBittorrent WebUI
is_qbittorrent_available() {
  CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://${GLUETUN_IP}:8080 2>/dev/null || echo "000")
  if [ "$CODE" = "200" ] || [ "$CODE" = "302" ]; then
    return 0
  fi
  return 1
}

# Try to reattach qBittorrent (and mousehole) to gluetun's network namespace
# by restarting those containers and waiting for the WebUI to come up.
try_reattach_qbittorrent() {
  echo "Attempting to reattach qBittorrent/mousehole to gluetun network..."
  docker restart qbittorrent_mouse mousehole 2>/dev/null || true
  sleep 5
  echo "Waiting for qBittorrent after reattach..."
  wait_for_qbittorrent || true
  is_qbittorrent_available && return 0 || return 1
}

login_qbittorrent() {
  curl -s -c /tmp/qbit_cookie -X POST \
    --data-urlencode "username=$QBIT_USER" \
    --data-urlencode "password=$QBIT_PASS" \
    http://${GLUETUN_IP}:8080/api/v2/auth/login >/dev/null 2>&1
}

apply_qbittorrent_settings() {
  echo "Setting qBittorrent to use tun0 interface..."
  curl -s -b /tmp/qbit_cookie \
    --data-urlencode 'json={"current_network_interface":"tun0"}' \
    http://${GLUETUN_IP}:8080/api/v2/app/setPreferences

  echo "Restarting qBittorrent to apply interface binding..."
  docker restart qbittorrent_mouse
  sleep 15

  # Re-login after restart since the old session cookie is now invalid
  login_qbittorrent
}

log_event() {
  _event="$1"
  _port="${2:-0}"
  _old_port="${3:-0}"
  _message="$4"
  _vpn_ip="${5:-}"
  if [ -n "$TZ" ]; then
    _ts=$(TZ="$TZ" date +"%Y-%m-%dT%H:%M:%S%z")
  else
    _ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  fi
  mkdir -p /data
  printf '{"timestamp":"%s","event":"%s","port":%s,"old_port":%s,"vpn_ip":"%s","message":"%s"}\n' \
    "$_ts" "$_event" "$_port" "$_old_port" "$_vpn_ip" "$_message" >> /data/port-history.json || true
}

get_vpn_ip() {
  curl -s -u "$GLUETUN_AUTH_USER:$GLUETUN_AUTH_PASS" \
    http://${GLUETUN_IP}:8000/v1/publicip/ip 2>/dev/null | \
    jq -r '.public_ip // empty'
}

# Stop dependent containers, restart gluetun, then bring everything back up.
# qbittorrent and mousehole share gluetun's network namespace — simply restarting
# gluetun leaves them with a broken network, so we must manage them explicitly.
restart_stack() {
  echo "Stopping qbittorrent and mousehole before gluetun restart..."
  docker stop qbittorrent_mouse mousehole 2>/dev/null || true

  echo "Restarting gluetun to obtain a new VPN port lease..."
  docker restart gluetun_mouse

  wait_for_gluetun || true

  echo "Starting qbittorrent and mousehole..."
  docker start qbittorrent_mouse mousehole

  wait_for_qbittorrent || true

  login_qbittorrent
  apply_qbittorrent_settings
}

# Print a friendly startup banner similar to other containers
print_banner() {
  NAME="port-updater"
  SERVICE_NAME="port-updater"
  CONTAINER_NAME="port_updater"
  VERSION="local build"
  # If TZ is provided via docker-compose, display local time in that zone.
  # Otherwise default to UTC.
  if [ -n "$TZ" ]; then
    STARTED_AT=$(TZ="$TZ" date +"%Y-%m-%d %H:%M:%S %Z")
  else
    STARTED_AT=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
  fi

  echo
  echo "============================================"
  echo ""
  echo "=============== ${NAME} ==============="
  echo ""
  echo "Service: ${SERVICE_NAME}  Container: ${CONTAINER_NAME}"
  echo "Version: ${VERSION}"
  echo "Started : ${STARTED_AT}"
  echo ""
  echo "--- Purpose: keep qBittorrent listen port in sync with VPN forwarded port ---"
  echo ""
  echo "============================================"
  echo
}

# --- Initial startup ---
print_banner
log_event "startup" "0" "0" "Port updater started"
echo "Waiting for qBittorrent to be ready..."
if ! wait_for_qbittorrent; then
  echo "qBittorrent did not become ready within timeout; attempting to reattach containers..."
  try_reattach_qbittorrent || true
fi

login_qbittorrent
apply_qbittorrent_settings

# --- Port monitoring loop ---
echo "Starting port monitoring loop..."
LAST_PORT=0
ZERO_PORT_COUNT=0
ZERO_PORT_LIMIT="${ZERO_PORT_LIMIT:-3}"
while true; do
  # Re-login periodically (cookie expires)
  # If qBittorrent is unreachable (often due to gluetun having restarted and
  # containers needing to reattach to the new network namespace), attempt a
  # lightweight reattach before continuing.
  if ! is_qbittorrent_available; then
    echo "qBittorrent unreachable from port-updater; attempting reattach..."
    try_reattach_qbittorrent || true
  fi
  login_qbittorrent

  # Get VPN forwarded port and current VPN public IP (use control server basic auth)
  PORT=$(curl -s -u "$GLUETUN_AUTH_USER:$GLUETUN_AUTH_PASS" http://${GLUETUN_IP}:8000/v1/portforward | jq -r '.port // empty')
  VPN_IP=$(get_vpn_ip)

  # Get current qBittorrent listen port
  QBIT_PORT=$(curl -s -b /tmp/qbit_cookie http://${GLUETUN_IP}:8080/api/v2/app/preferences | jq -r '.listen_port // empty')

  # Update if: forwarded port changed, or qBit port is unset (1) or empty (e.g. after a restart)
  if [ -n "$PORT" ] && [ "$PORT" != "0" ] && { [ "$PORT" != "$LAST_PORT" ] || [ "$QBIT_PORT" = "1" ] || [ -z "$QBIT_PORT" ]; }; then
    echo ">>>"
    echo "      ProtonVPN assigned a new forwarded port: $PORT (was: $LAST_PORT) — triggering qBittorrent update"
    echo "<<<"
    echo "Port update needed: VPN=$PORT, qBit=$QBIT_PORT (last=$LAST_PORT)"
    curl -s -b /tmp/qbit_cookie \
      --data-urlencode "json={\"listen_port\":$PORT}" \
      http://${GLUETUN_IP}:8080/api/v2/app/setPreferences
    echo "Port updated to $PORT"
    log_event "port_update" "$PORT" "$LAST_PORT" "ProtonVPN assigned new port $PORT (was $LAST_PORT)" "$VPN_IP"
    LAST_PORT=$PORT
    ZERO_PORT_COUNT=0

    echo "Reannouncing all torrents..."
    curl -s -b /tmp/qbit_cookie -X POST \
      -d "hashes=all" \
      http://${GLUETUN_IP}:8080/api/v2/torrents/reannounce
    echo "Reannounce triggered."

  elif [ -z "$PORT" ] || [ "$PORT" = "0" ]; then
    ZERO_PORT_COUNT=$((ZERO_PORT_COUNT + 1))
    echo "Port is 0 ($ZERO_PORT_COUNT/$ZERO_PORT_LIMIT): VPN=$PORT, qBit=$QBIT_PORT"
    log_event "zero_port" "0" "$LAST_PORT" "Port is 0 ($ZERO_PORT_COUNT/$ZERO_PORT_LIMIT)" "$VPN_IP"
    if [ "$ZERO_PORT_COUNT" -ge "$ZERO_PORT_LIMIT" ]; then
      echo "Port has been 0 for $(( ZERO_PORT_COUNT * CHECK_INTERVAL / 60 )) minutes — restarting stack..."
      log_event "stack_restart" "0" "$LAST_PORT" "Port remained 0 for ${ZERO_PORT_COUNT} cycles — restarting stack" "$VPN_IP"
      restart_stack
      ZERO_PORT_COUNT=0
      LAST_PORT=0
      echo "Stack restarted. Checking for new port immediately..."
      continue
    else
      echo "Port is 0 — will retry in $ZERO_RETRY_INTERVAL seconds (faster retry)..."
      sleep $ZERO_RETRY_INTERVAL
      continue
    fi

  else
    echo "Port OK: VPN=$PORT, qBit=$QBIT_PORT"
  fi
  sleep $CHECK_INTERVAL
done
