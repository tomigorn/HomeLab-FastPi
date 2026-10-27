#!/usr/bin/env bash
# Copy beefy's idle-watcher metrics into the node-exporter textfile dir; remove them when beefy is down or sends nothing valid. Never wakes beefy (beefy-direct).
set -u
DEST=${DEST:-/var/lib/node-exporter/textfile/beefy_idle.prom}
SRC=${SRC:-/run/beefy-idle.prom}
tmp=$(mktemp "$DEST.XXXXXX") || exit 1
trap 'rm -f "$tmp"' EXIT
if ssh -o BatchMode=yes -o ConnectTimeout=5 "${HOST:-beefy-direct}" "cat $SRC" > "$tmp" 2>/dev/null \
    && grep -q '^beefy_idle_busy{' "$tmp"; then
    chmod 0644 "$tmp"
    mv "$tmp" "$DEST"
else
    rm -f "$DEST"
fi
