#!/bin/sh
set -e

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
    CODE=$(curl -s -o /dev/null -w "%{http_code}" http://172.32.0.2:8080 2>/dev/null)
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

login_qbittorrent() {
  curl -s -c /tmp/qbit_cookie -X POST \
    --data-urlencode "username=$QBIT_USER" \
    --data-urlencode "password=$QBIT_PASS" \
    http://172.32.0.2:8080/api/v2/auth/login >/dev/null 2>&1
}

apply_qbittorrent_settings() {
  echo "Setting qBittorrent to use tun0 interface..."
  curl -s -b /tmp/qbit_cookie \
    --data-urlencode 'json={"current_network_interface":"tun0"}' \
    http://172.32.0.2:8080/api/v2/app/setPreferences

  echo "Restarting qBittorrent to apply interface binding..."
  docker restart qbittorrent_mouse
  sleep 15

  # Re-login after restart since the old session cookie is now invalid
  login_qbittorrent
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

# --- Initial startup ---
echo "Waiting for qBittorrent to be ready..."
wait_for_qbittorrent || true

login_qbittorrent
apply_qbittorrent_settings

# --- Port monitoring loop ---
echo "Starting port monitoring loop..."
LAST_PORT=0
ZERO_PORT_COUNT=0
ZERO_PORT_LIMIT=3
while true; do
  # Re-login periodically (cookie expires)
  login_qbittorrent

  # Get VPN forwarded port (use control server basic auth)
  PORT=$(curl -s -u "$GLUETUN_AUTH_USER:$GLUETUN_AUTH_PASS" http://172.32.0.2:8000/v1/portforward | sed -n 's/.*"port":[ ]*\([0-9]*\).*/\1/p')

  # Get current qBittorrent listen port
  QBIT_PORT=$(curl -s -b /tmp/qbit_cookie http://172.32.0.2:8080/api/v2/app/preferences | sed -n 's/.*"listen_port":\s*\([0-9]*\).*/\1/p')

  # Update if: forwarded port changed, or qBit port is unset (1) or empty (e.g. after a restart)
  if [ -n "$PORT" ] && [ "$PORT" != "0" ] && { [ "$PORT" != "$LAST_PORT" ] || [ "$QBIT_PORT" = "1" ] || [ -z "$QBIT_PORT" ]; }; then
    echo ">>>"
    echo "      ProtonVPN assigned a new forwarded port: $PORT (was: $LAST_PORT) — triggering qBittorrent update"
    echo "<<<"
    echo "Port update needed: VPN=$PORT, qBit=$QBIT_PORT (last=$LAST_PORT)"
    curl -s -b /tmp/qbit_cookie \
      --data-urlencode "json={\"listen_port\":$PORT}" \
      http://172.32.0.2:8080/api/v2/app/setPreferences
    echo "Port updated to $PORT"
    LAST_PORT=$PORT
    ZERO_PORT_COUNT=0

    echo "Reannouncing all torrents..."
    curl -s -b /tmp/qbit_cookie -X POST \
      -d "hashes=all" \
      http://172.32.0.2:8080/api/v2/torrents/reannounce
    echo "Reannounce triggered."

  elif [ -z "$PORT" ] || [ "$PORT" = "0" ]; then
    ZERO_PORT_COUNT=$((ZERO_PORT_COUNT + 1))
    echo "Port is 0 ($ZERO_PORT_COUNT/$ZERO_PORT_LIMIT): VPN=$PORT, qBit=$QBIT_PORT"
    if [ "$ZERO_PORT_COUNT" -ge "$ZERO_PORT_LIMIT" ]; then
      echo "Port has been 0 for $(( ZERO_PORT_COUNT * CHECK_INTERVAL / 60 )) minutes — restarting stack..."
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
