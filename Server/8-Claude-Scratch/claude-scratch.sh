#!/usr/bin/env bash
# Keeps Claude Code's scratch (/tmp/claude-1000) on the NVMe instead of the RAM-backed /tmp: moves what is there to disk, then bind-mounts the disk folder over it. Idempotent.
set -euo pipefail
SRC=${SCRATCH_SRC:-/tmp/claude-1000}
DST=${SCRATCH_DST:-/home/pi/.cache/claude-tmp}
OWNER=${SCRATCH_OWNER:-pi}
mountpoint -q "$SRC" && exit 0
# a parent without the owner's x bit (once set by mistake) would leave the mounted scratch unusable for the owner
[[ -d ${DST%/*} ]] && chmod u+rwx "${DST%/*}"
install -d -o "$OWNER" -g "$(id -gn "$OWNER")" -m 0700 "$DST"
if [[ -d $SRC ]]; then
  rsync -a --remove-source-files "$SRC"/ "$DST"/
  find "$SRC" -mindepth 1 -depth -type d -empty -delete
  chmod 0700 "$DST"
else
  install -d -o "$OWNER" -g "$(id -gn "$OWNER")" -m 0700 "$SRC"
fi
mount -o bind,nosuid,nodev "$DST" "$SRC"
