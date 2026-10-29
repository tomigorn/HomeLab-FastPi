#!/usr/bin/env bash
# Copy beefy's idle-watcher metrics into the node-exporter textfile dir; remove them when beefy is down or sends nothing valid. Never wakes beefy (beefy-direct).
# Also copies the queue-watchdog digest events (daily digest), the storage figures (storage.prom), the SSD->HDD mover result (mover.prom), SMART (smart-exporter), the request/download/indexer figures (media-metrics) and the Jellyfin popular job (jf_popular_*, optional); those copies stay while beefy sleeps (nothing changes while it is off), their series carry their own timestamps.
# Each copy is validated: only that file's metric names, any host label must be beefy, families fastpi writes too (smart_*, indexer_*) need host="beefy"; one bad line rejects the whole file (old copy kept), so a compromised beefy cannot shadow fastpi's own series.
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

MAX_BYTES=${MAX_BYTES:-262144}

# valid <file> <allowed names> <shared names>: every line is a sample, HELP/TYPE or comment of an allowed metric; any host label is "beefy"; shared names (families fastpi writes too) need host="beefy" and no HELP/TYPE
valid() {
    [[ $(stat -c %s "$1") -le $MAX_BYTES ]] || return 1
    awk -v allow="^($2)\$" -v shared="^($3)\$" '
        BEGIN { name = "^[a-zA-Z_:][a-zA-Z0-9_:]*"; lbl = "^[a-zA-Z_][a-zA-Z0-9_]*=\"([^\"\\\\]|\\\\.)*\""
                num = "^[-+]?([0-9]+(\\.[0-9]*)?([eE][-+]?[0-9]+)?|\\.[0-9]+([eE][-+]?[0-9]+)?|NaN|[-+]?Inf)$" }
        function fail() { bad = 1; exit }
        /^[ \t]*$/ { next }
        /^# (HELP|TYPE) / { if ($3 !~ allow || $3 ~ shared) fail(); next }
        /^#/ { next }
        {
            line = $0
            if (!match(line, name)) fail()
            metric = substr(line, 1, RLENGTH); line = substr(line, RLENGTH + 1)
            if (metric !~ allow) fail()
            hosts = 0; host = ""
            if (substr(line, 1, 1) == "{") {
                line = substr(line, 2)
                while (substr(line, 1, 1) != "}") {
                    if (!match(line, lbl)) fail()
                    pair = substr(line, 1, RLENGTH); line = substr(line, RLENGTH + 1)
                    if (pair ~ /^host=/) { hosts++; host = pair }
                    if (substr(line, 1, 1) == ",") line = substr(line, 2)
                    else if (substr(line, 1, 1) != "}") fail()
                }
                line = substr(line, 2)
            }
            if (hosts > 1 || (hosts == 1 && host != "host=\"beefy\"")) fail()
            if (metric ~ shared && hosts != 1) fail()
            n = split(line, f, /[ \t]+/)
            if (f[1] != "" || n < 2 || n > 3 || f[2] !~ num || (n == 3 && f[3] !~ /^-?[0-9]+$/)) fail()
        }
        END { exit bad }' "$1"
}

# fetch <remote file> <dest> <required line prefix> <allowed names> [<shared names>]: replace dest only with a valid copy
fetch() {
    local tmp
    tmp=$(mktemp "$2.XXXXXX") || return 1
    if ssh -o BatchMode=yes -o ConnectTimeout=5 "${HOST:-beefy-direct}" "head -c $((MAX_BYTES + 1)) $1" > "$tmp" 2>/dev/null \
        && grep -q "^$3" "$tmp" && valid "$tmp" "$4" "${5:-^\$}"; then
        chmod 0644 "$tmp"
        mv "$tmp" "$2"
    else
        rm -f "$tmp"
        return 1
    fi
}

fetch "$SRC" "$DEST" 'beefy_idle_busy{' 'beefy_idle_[a-z_]+|beefy_boot_time_seconds' || { rm -f "$DEST"; exit 0; }
fetch "$WD_SRC" "$WD_DEST" 'beefy_watchdog_digest_updated_timestamp_seconds ' 'beefy_watchdog_[a-z_]+' || true
fetch "$ST_SRC" "$ST_DEST" 'beefy_storage_updated_timestamp_seconds ' 'beefy_storage_[a-z_]+' || true
fetch "$MV_SRC" "$MV_DEST" 'beefy_mover_last_run_timestamp_seconds ' 'beefy_mover_[a-z_]+|beefy_disk_smart_raw' || true
fetch "$SM_SRC" "$SM_DEST" 'smart_exporter_last_run_timestamp_seconds{' 'smart_[a-z_]+' 'smart_[a-z_]+' || true
fetch "$MM_SRC" "$MM_DEST" 'beefy_media_metrics_updated_timestamp_seconds ' 'beefy_(downloads_[a-z_]+|requests|request_badges|media_metrics_[a-z_]+)|indexer_(used|limit|bar_[a-z_]+)' 'indexer_[a-z_]+' || true
fetch "$JP_SRC" "$JP_DEST" 'jf_popular_last_run_timestamp_seconds ' 'jf_popular_[a-z_]+' || true
