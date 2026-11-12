#!/usr/bin/env bash
# Daily copy of tower's Unraid flash config (/boot/config: licence key, array
# config, shares, users, plugins, secrets) to fastpi, so a dead USB stick is a
# 10-minute restore (new stick + copy config back) instead of a rebuild.
#
# Pull-based, from fastpi, and it NEVER wakes tower: it tries a direct ssh to
# the IP and only runs when tower is already up. An hourly
# timer calls it; it no-ops once today's snapshot exists. Dated snapshots are
# hard-linked against the previous one (cp -al), so 30 days cost ~1 copy.
#
# Restore: copy <snapshot>/ onto a fresh Unraid USB stick's /config
# (make-bootable with the USB creator first), then Tools -> Registration ->
# Replace Key if the stick's GUID changed.
set -euo pipefail

TOWER_IP=192.168.1.101
TOWER_KEY="$HOME/.ssh/tower"
DEST="${DEST:-$HOME/backups/tower-flash}"
TEXTFILE_DIR="${TEXTFILE_DIR:-/var/lib/node-exporter/textfile}"
KEEP_DAYS=30
SSH_OPTS=(-i "$TOWER_KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=5)

today="${TODAY:-$(date +%F)}"
log() { echo "tower-flash-backup: $*"; }

[[ -d "$DEST/$today" ]] && { log "already have $today"; exit 0; }

# Non-waking liveness check: direct ssh to the IP never wakes tower. What must
# NOT be used is `ssh tower` (its Match block fires a WoL).
if ! ssh "${SSH_OPTS[@]}" "root@$TOWER_IP" true >/dev/null 2>&1; then
  log "tower is asleep; skipping (will retry on the next timer run)"; exit 0
fi

mkdir -p "$DEST" && chmod 700 "$DEST"
tmp="$DEST/.incoming"
rm -rf "$tmp"
mkdir -p "$tmp"
if [[ -d "$DEST/latest" ]]; then cp -al "$DEST/latest/." "$tmp/"; fi
rsync -a --delete --no-perms --no-owner --no-group --chmod=D700,F600 \
  -e "ssh ${SSH_OPTS[*]}" \
  "root@$TOWER_IP:/boot/config/" "$tmp/"
chmod -R go-rwx "$tmp"   # the tree holds passwd/shadow/secrets/ssh keys
mv "$tmp" "$DEST/$today"
ln -sfn "$today" "$DEST/latest"
if [[ -d $TEXTFILE_DIR ]]; then
  m="$TEXTFILE_DIR/.tower_flash_backup.prom.$$"
  printf '# TYPE tower_flash_backup_last_success_timestamp_seconds gauge\ntower_flash_backup_last_success_timestamp_seconds %s\n' "$(date +%s)" > "$m" \
    && chmod 644 "$m" && mv "$m" "$TEXTFILE_DIR/tower_flash_backup.prom"
fi
log "snapshot $today done ($(du -sh "$DEST/$today" | cut -f1), key: $(ls "$DEST/$today"/*.key 2>/dev/null | xargs -n1 basename | tr '\n' ' '))"

# retention
find "$DEST" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +"$KEEP_DAYS" -exec rm -rf {} + 2>/dev/null || true
