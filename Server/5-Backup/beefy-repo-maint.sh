#!/usr/bin/env bash
# Retention, prune and check of beefy's append-only restic repo on fastpi, plus its metrics (beefy-backup.prom). Runs as root from beefy-repo-maint.service and hands the repo back to the REST server user; beefy itself cannot delete anything.
set -uo pipefail
REPO=${REPO:-/var/lib/beefy-backup/beefy}
PROM=${PROM:-/var/lib/node-exporter/textfile/beefy-backup.prom}
OWNER=${OWNER:-beefy-backup:beefy-backup}
export RESTIC_PASSWORD_FILE=${RESTIC_PASSWORD_FILE:-/root/.config/restic/beefy-repo.pass}
export RESTIC_REPOSITORY=$REPO
DOW=${DOW:-$(date +%u)}
R() { restic --retry-lock 20m "$@"; }
log() { echo "beefy-repo-maint: $*"; }

STATUS=0 ERRORS=0 LAST=0 LBYTES=0 COUNT=0 RBYTES=0
write_metric() {
    cat > "$PROM.tmp" <<EOM
# TYPE beefy_backup_last_snapshot_timestamp_seconds gauge
beefy_backup_last_snapshot_timestamp_seconds $LAST
# TYPE beefy_backup_last_snapshot_bytes gauge
beefy_backup_last_snapshot_bytes $LBYTES
# TYPE beefy_backup_snapshots gauge
beefy_backup_snapshots $COUNT
# TYPE beefy_backup_repo_bytes gauge
beefy_backup_repo_bytes $RBYTES
# TYPE beefy_backup_maint_last_run_timestamp_seconds gauge
beefy_backup_maint_last_run_timestamp_seconds $(date +%s)
# TYPE beefy_backup_maint_last_status gauge
# 1 ok, 0 failed
beefy_backup_maint_last_status $STATUS
EOM
    chmod 644 "$PROM.tmp"; mv "$PROM.tmp" "$PROM"
}
trap write_metric EXIT

R forget --host beefy --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --group-by host,tags || { log "forget failed"; ERRORS=$((ERRORS+1)); }
if [ "$DOW" = 7 ]; then R prune || { log "prune failed"; ERRORS=$((ERRORS+1)); }; fi
if [ "$DOW" = 3 ]; then R check --read-data-subset=1/10 || { log "check failed"; ERRORS=$((ERRORS+1)); }; fi

SNAPS=$(R snapshots --host beefy --json 2>/dev/null) || { log "snapshots failed"; ERRORS=$((ERRORS+1)); SNAPS='[]'; }
COUNT=$(jq 'length' <<<"$SNAPS" 2>/dev/null || echo 0)
NEWEST=$(jq -c 'sort_by(.time) | last // empty' <<<"$SNAPS" 2>/dev/null)
if [ -n "$NEWEST" ]; then
    LAST=$(date -d "$(jq -r .time <<<"$NEWEST")" +%s)
    LBYTES=$(jq -r '.summary.total_bytes_processed // 0' <<<"$NEWEST")
else
    log "no beefy snapshot in the repo"; ERRORS=$((ERRORS+1))
fi
chown -R "$OWNER" "$REPO" || { log "chown failed"; ERRORS=$((ERRORS+1)); }
RBYTES=$(du -sb "$REPO" 2>/dev/null | awk '{print $1}'); RBYTES=${RBYTES:-0}

[ "$ERRORS" -eq 0 ] && STATUS=1
log "finished status=$STATUS snapshots=$COUNT repo=$RBYTES"
[ "$STATUS" = 1 ]
