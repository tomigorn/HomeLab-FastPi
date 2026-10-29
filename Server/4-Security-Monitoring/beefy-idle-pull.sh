#!/usr/bin/env bash
# Copy beefy's idle-watcher metrics into the node-exporter textfile dir; remove them when beefy is down or sends nothing valid. Never wakes beefy (beefy-direct).
# Also copies the queue-watchdog digest events (daily digest), the storage figures (storage.prom), the SSD->HDD mover result (mover.prom), SMART (smart-exporter), the request/download/indexer figures (media-metrics) and the Jellyfin popular job (jf_popular_*, optional); those copies stay while beefy sleeps (nothing changes while it is off), their series carry their own timestamps.
set -u
DEST=${DEST:-/var/lib/node-exporter/textfile/beefy_idle.prom}
SRC=${SRC:-/run/beefy-idle.prom}
WD_DEST=${WD_DEST:-/var/lib/node-exporter/textfile/beefy_watchdog.prom}
WD_SRC=${WD_SRC:-/home/buntu/.local/state/movie-downloads/watchdog-digest.prom}
ST_DEST=${ST_DEST:-/var/lib/node-exporter/textfile/beefy_storage.prom}
ST_SRC=${ST_SRC:-/home/buntu/.local/state/indexer-bar/storage.prom}
MV_DEST=${MV_DEST:-/var/lib/node-exporter/textfile/beefy_mover.prom}
MV_SRC=${MV_SRC:-/var/lib/beefy-mover/mover.prom}
SM_DEST=${SM_DEST:-/var/lib/node-exporter/textfile/smart_beefy.prom}
SM_SRC=${SM_SRC:-/var/lib/smart-exporter/smart_beefy.prom}
MM_DEST=${MM_DEST:-/var/lib/node-exporter/textfile/beefy_media.prom}
MM_SRC=${MM_SRC:-/home/buntu/.local/state/movie-downloads/media-metrics.prom}
JP_DEST=${JP_DEST:-/var/lib/node-exporter/textfile/beefy_jellyfin_popular.prom}
JP_SRC=${JP_SRC:-/home/buntu/.local/state/jellyfin-popular.prom}

# fetch <remote file> <dest> <required line prefix>: replace dest only with a valid copy
fetch() {
    local tmp
    tmp=$(mktemp "$2.XXXXXX") || return 1
    if ssh -o BatchMode=yes -o ConnectTimeout=5 "${HOST:-beefy-direct}" "cat $1" > "$tmp" 2>/dev/null \
        && grep -q "^$3" "$tmp"; then
        chmod 0644 "$tmp"
        mv "$tmp" "$2"
    else
        rm -f "$tmp"
        return 1
    fi
}

fetch "$SRC" "$DEST" 'beefy_idle_busy{' || { rm -f "$DEST"; exit 0; }
fetch "$WD_SRC" "$WD_DEST" 'beefy_watchdog_digest_updated_timestamp_seconds ' || true
fetch "$ST_SRC" "$ST_DEST" 'beefy_storage_updated_timestamp_seconds ' || true
fetch "$MV_SRC" "$MV_DEST" 'beefy_mover_last_run_timestamp_seconds ' || true
fetch "$SM_SRC" "$SM_DEST" 'smart_exporter_last_run_timestamp_seconds{' || true
fetch "$MM_SRC" "$MM_DEST" 'beefy_media_metrics_updated_timestamp_seconds ' || true
fetch "$JP_SRC" "$JP_DEST" 'jf_popular_last_run_timestamp_seconds ' || true
