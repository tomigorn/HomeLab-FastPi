#!/bin/sh
mkdir -p /data
python3 /usr/local/bin/web-server.py &
exec /usr/local/bin/port-updater.sh
