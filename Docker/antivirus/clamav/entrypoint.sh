#!/bin/sh
set -e

DB_DIR=/var/lib/clamav
QUARANTINE=/scan/quarantine
WATCH_DIRS="/scan/sabnzbd/complete /scan/qbittorrent/complete"

mkdir -p "$QUARANTINE"
for d in $WATCH_DIRS; do mkdir -p "$d"; done

# First-run: fetch definitions if the volume is empty.
if [ ! -f "${DB_DIR}/main.cvd" ] && [ ! -f "${DB_DIR}/main.cld" ]; then
    echo "[entrypoint] No virus definitions found — downloading now (a few minutes)..."
    freshclam --config-file=/etc/clamav/freshclam.conf --no-dns || true
fi

# Keep definitions updated. freshclam is light and does NOT hold the scan DB
# resident in RAM the way clamd did.
freshclam --daemon --config-file=/etc/clamav/freshclam.conf &

echo "[entrypoint] Watching for completed downloads in: $WATCH_DIRS"
echo "[entrypoint] Infected files will be moved to: $QUARANTINE"

# Event-driven: fires when a finished job is written/moved into complete/.
# clamscan loads the DB, scans, and exits — so RAM is used only during a scan.
inotifywait -m -r -e close_write -e moved_to --format '%w%f' $WATCH_DIRS 2>/dev/null | while read TARGET; do
    case "$TARGET" in "$QUARANTINE"/*) continue ;; esac
    sleep 5   # debounce: let a multi-file job settle
    [ -e "$TARGET" ] || continue
    echo "[scan] $(date -Is) scanning: $TARGET"
    if clamscan -r -i --move="$QUARANTINE" "$TARGET"; then
        echo "[scan] CLEAN: $TARGET"
    else
        rc=$?
        if [ "$rc" -eq 1 ]; then
            echo "[scan] !!!! INFECTED — moved to quarantine: $TARGET"
        else
            echo "[scan] scan ERROR (rc=$rc): $TARGET"
        fi
    fi
done
