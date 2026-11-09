#!/bin/sh
# VAR_FILE=/path sets VAR from that file (docker secrets convention)
for var in QBIT_PASS GLUETUN_AUTH_PASS WEB_PASS; do
  eval "file=\${${var}_FILE:-}"
  if [ -n "$file" ]; then
    export "$var=$(cat "$file")"
    unset "${var}_FILE"
  fi
done
mkdir -p /data
python3 /usr/local/bin/web-server.py &
exec /usr/local/bin/port-updater.sh
