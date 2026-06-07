#!/bin/sh
set -e

DB_DIR=/var/lib/clamav

# Download definitions on first start
if [ ! -f "${DB_DIR}/main.cvd" ] && [ ! -f "${DB_DIR}/main.cld" ]; then
    echo "[entrypoint] No virus definitions found — downloading now (this takes a few minutes)..."
    freshclam --config-file=/etc/clamav/freshclam.conf --no-dns
fi

# Start freshclam in daemon mode for automatic hourly updates
freshclam --daemon --config-file=/etc/clamav/freshclam.conf &

echo "[entrypoint] Starting clamd..."
exec clamd --foreground --config-file=/etc/clamav/clamd.conf
