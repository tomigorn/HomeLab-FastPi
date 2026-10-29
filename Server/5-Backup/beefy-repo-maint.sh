#!/usr/bin/env bash
# Retention, prune and check of beefy's append-only restic repo on fastpi, plus its metrics (beefy-backup.prom). Runs from beefy-repo-maint.service as the REST server user beefy-backup (password as a systemd credential), so every file it writes stays readable for rest-server; beefy itself cannot delete anything.
set -uo pipefail
REPO=${REPO:-/var/lib/beefy-backup/beefy}
PROM=${PROM:-/var/lib/node-exporter/textfile/beefy-backup.prom}
export RESTIC_PASSWORD_FILE=${RESTIC_PASSWORD_FILE:-${CREDENTIALS_DIRECTORY:-/run/credentials/beefy-repo-maint.service}/beefy-repo.pass}
export RESTIC_REPOSITORY=$REPO
DOW=${DOW:-$(date +%u)}
R() { restic --retry-lock 20m "$@"; }
log() { echo "beefy-repo-maint: $*"; }
if [ "${RUN_UID:-$(id -u)}" = 0 ]; then log "not as root (root-owned repo files break beefy's backups): sudo systemctl start beefy-repo-maint"; exit 2; fi

STATUS=0 ERRORS=0 LAST=0 LBYTES=0 COUNT=0 RBYTES=0 FUTURE=0
NOW=${NOW:-$(date +%s)}
num() { [[ $1 =~ ^[0-9]+$ ]] && echo "$1" || echo 0; }
write_metric() {
    cat > "$PROM.tmp" <<EOM
# TYPE beefy_backup_last_snapshot_timestamp_seconds gauge
beefy_backup_last_snapshot_timestamp_seconds $(num "$LAST")
# TYPE beefy_backup_last_snapshot_bytes gauge
beefy_backup_last_snapshot_bytes $(num "$LBYTES")
# TYPE beefy_backup_snapshots gauge
beefy_backup_snapshots $(num "$COUNT")
# TYPE beefy_backup_future_snapshots gauge
# snapshots of any host dated more than 1 h ahead (forget refused while > 0)
beefy_backup_future_snapshots $(num "$FUTURE")
# TYPE beefy_backup_repo_bytes gauge
beefy_backup_repo_bytes $(num "$RBYTES")
# TYPE beefy_backup_maint_last_run_timestamp_seconds gauge
beefy_backup_maint_last_run_timestamp_seconds $(date +%s)
# TYPE beefy_backup_maint_last_status gauge
# 1 ok, 0 failed
beefy_backup_maint_last_status $STATUS
EOM
    chmod 644 "$PROM.tmp"; mv "$PROM.tmp" "$PROM"
}
trap write_metric EXIT

# epochs <snapshots json>: "<epoch|bad> <hostname> <index>" per snapshot
epochs() {
    local i=0 host t e
    while IFS=$'\t' read -r host t; do
        e=$(date -d "$t" +%s 2>/dev/null) && [[ $e =~ ^[0-9]+$ ]] || e=bad
        echo "$e $host $i"; i=$((i+1))
    done < <(jq -r '.[] | [.hostname // "", .time // ""] | @tsv' <<<"$1" 2>/dev/null)
}

# Snapshot times are chosen by the client (restic backup --time): future-dated ones would let time-based retention forget every real snapshot, so forget waits until they are gone.
SAFE=0
if ALL=$(R snapshots --json 2>/dev/null) && jq -e 'type == "array"' <<<"$ALL" >/dev/null 2>&1; then
    E=$(epochs "$ALL")
    FUTURE=$(awk -v lim=$((NOW + 3600)) '$1 != "bad" && $1 > lim' <<<"$E" | grep -c .)
    BADT=$(awk '$1 == "bad"' <<<"$E" | grep -c .)
    if [ "$FUTURE" -gt 0 ] || [ "$BADT" -gt 0 ]; then
        log "refusing forget/prune: $FUTURE snapshot(s) dated more than 1 h ahead, $BADT with an unreadable time"; ERRORS=$((ERRORS+1))
    else
        SAFE=1
    fi
else
    log "snapshots failed, no forget"; ERRORS=$((ERRORS+1))
fi
if [ "$SAFE" = 1 ]; then
    R forget --host beefy --keep-within 30d --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --group-by host,tags || { log "forget failed"; ERRORS=$((ERRORS+1)); }
    if [ "$DOW" = 7 ]; then R prune || { log "prune failed"; ERRORS=$((ERRORS+1)); }; fi
fi
if [ "$DOW" = 3 ]; then R check --read-data-subset=1/10 || { log "check failed"; ERRORS=$((ERRORS+1)); }; fi

SNAPS=$(R snapshots --host beefy --json 2>/dev/null) || { log "snapshots failed"; ERRORS=$((ERRORS+1)); SNAPS='[]'; }
COUNT=$(jq 'length' <<<"$SNAPS" 2>/dev/null || echo 0)
NEWEST=$(epochs "$SNAPS" | awk -v lim=$((NOW + 3600)) '$2 == "beefy" && $1 != "bad" && $1 <= lim' | sort -n | tail -1)
if [ -n "$NEWEST" ]; then
    LAST=${NEWEST%% *}
    LBYTES=$(jq -r --argjson i "${NEWEST##* }" '.[$i].summary.total_bytes_processed // 0' <<<"$SNAPS")
else
    log "no beefy snapshot with a valid time in the repo"; ERRORS=$((ERRORS+1))
fi
RBYTES=$(du -sb "$REPO" 2>/dev/null | awk '{print $1}'); RBYTES=${RBYTES:-0}

[ "$ERRORS" -eq 0 ] && STATUS=1
log "finished status=$STATUS snapshots=$COUNT repo=$RBYTES"
[ "$STATUS" = 1 ]
