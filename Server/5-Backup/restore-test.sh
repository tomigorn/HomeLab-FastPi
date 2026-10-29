#!/usr/bin/env bash
# Monthly restore test of the fastpi restic backup: restic check, restore into scratch, SQLite and Authentik checks, Telegram summary. Runs as root from fastpi-restore-test.service; never touches live data.
set -uo pipefail

CONF=/root/.config/restic
export RESTIC_PASSWORD_FILE=$CONF/fastpi.pass
export RESTIC_REPOSITORY=sftp:buntu@beefy.homelab:/home/buntu/backups/fastpi-restic
export RESTIC_CACHE_DIR=/var/cache/restic
SSHC="ssh -i $CONF/beefy_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=10 -o UserKnownHostsFile=$CONF/known_hosts -o StrictHostKeyChecking=yes buntu@beefy.homelab -s sftp"
WORK_BASE=${WORK_BASE:-/var/tmp}
PROM=${PROM:-/var/lib/node-exporter/textfile/backup-restore-test.prom}
OOB=${OOB:-/home/pi/Projects/Docker/_global/scripts/oob-alert.sh}
LIVE_ROOT=${LIVE_ROOT:-}
BEEFY_TCP=${BEEFY_TCP:-/dev/tcp/192.168.1.102/22}
LOCK=${LOCK:-/run/fastpi-backup.lock}
STAGE=/var/lib/fastpi-backup-staging
INCLUDES=(
    "$STAGE"
    /home/pi/Projects/Docker/docker-compose.yaml
    /home/pi/Projects/Docker/Traefik/traefik
    /home/pi/Projects/Server
    /etc/ssh /etc/systemd/system /etc/iptables
)
COUNTS="select 'users', count(*) from authentik_core_user union all select 'groups', count(*) from authentik_core_group union all select 'apps', count(*) from authentik_core_application"

R() { restic -o sftp.command="$SSHC" "$@"; }
log() { echo "restore-test: $*"; }
esc() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' <<<"$*"; }

START=$(date +%s)
STATUS=0 AGE=0 BYTES=0 RSECS=0
FAILS=() NOTES=()
WORK="" PG=""
fail() { FAILS+=("$(esc "$*")"); log "FAIL $*"; }
note() { NOTES+=("$(esc "$*")"); log "$*"; }

write_metric() {
    local now; now=$(date +%s)
    cat > "$PROM.tmp" <<EOM
# TYPE backup_restore_test_last_run_timestamp_seconds gauge
backup_restore_test_last_run_timestamp_seconds $now
# TYPE backup_restore_test_last_status gauge
# 1 ok, 0 failed, 2 skipped (beefy asleep)
backup_restore_test_last_status $STATUS
# TYPE backup_restore_test_snapshot_age_seconds gauge
backup_restore_test_snapshot_age_seconds $AGE
# TYPE backup_restore_test_restore_bytes gauge
backup_restore_test_restore_bytes $BYTES
# TYPE backup_restore_test_restore_seconds gauge
backup_restore_test_restore_seconds $RSECS
# TYPE backup_restore_test_duration_seconds gauge
backup_restore_test_duration_seconds $((now-START))
EOM
    chmod 644 "$PROM.tmp"; mv "$PROM.tmp" "$PROM"
}
cleanup() {
    [ -n "$PG" ] && docker rm -f "$PG" >/dev/null 2>&1
    [ -n "$WORK" ] && rm -rf -- "$WORK"
    write_metric
}
trap cleanup EXIT
trap 'log "terminated"; exit 1' TERM INT

if ! timeout 5 bash -c "< $BEEFY_TCP" 2>/dev/null; then
    log "beefy unreachable (asleep), skipped"; STATUS=2; exit 0
fi
exec 9>"$LOCK"
flock -w 300 9 || { log "backup still running, skipped"; STATUS=2; exit 0; }

R check --read-data-subset=5% >/dev/null 2>&1 || fail "restic check --read-data-subset=5% failed"

SNAP=$(R snapshots latest --tag nightly --host fastpi --json 2>/dev/null)
STIME=$(jq -r '.[0].time // empty' <<<"$SNAP" 2>/dev/null)
SID=$(jq -r '.[0].short_id // empty' <<<"$SNAP" 2>/dev/null)
if [ -z "$STIME" ]; then
    fail "no nightly snapshot found"
else
    SEPOCH=$(date -d "$STIME" +%s)
    AGE=$(( ${NOW:-$(date +%s)} - SEPOCH ))
    [ "$AGE" -gt $((48*3600)) ] && note "latest snapshot is $((AGE/3600)) h old"
fi

umask 077
WORK=$(mktemp -d "$WORK_BASE/fastpi-restore-test.XXXXXX")
if [ -n "$STIME" ]; then
    inc=(); for p in "${INCLUDES[@]}"; do inc+=(--include "$p"); done
    t0=$(date +%s)
    if R restore "$SID" --target "$WORK" "${inc[@]}" >/dev/null 2>&1; then
        RSECS=$(( $(date +%s) - t0 ))
        BYTES=$(du -sb "$WORK" | awk '{print $1}')
    else
        fail "restic restore failed"
    fi
fi

NDB=0
while IFS= read -r -d '' db; do
    NDB=$((NDB+1))
    r=$(sqlite3 -readonly "$db" "pragma quick_check" 2>&1 | head -1)
    [ "$r" = ok ] || fail "SQLite ${db#"$WORK$STAGE/sqlite"}: $r"
done < <(find "$WORK$STAGE/sqlite" -type f -print0 2>/dev/null)
[ "$NDB" -gt 0 ] || [ -z "$STIME" ] || fail "no SQLite dumps in the snapshot"

NDIFF=0 NCMP=0
if [ -n "$STIME" ]; then
    while IFS= read -r -d '' f; do
        rel=${f#"$WORK"}
        case "$rel" in "$STAGE"/*) continue ;; esac
        live="$LIVE_ROOT$rel"
        [ -f "$live" ] && [ ! -L "$live" ] || continue
        [ "$(stat -c %Y "$live")" -lt "$SEPOCH" ] || continue
        NCMP=$((NCMP+1))
        cmp -s "$f" "$live" || { NDIFF=$((NDIFF+1)); fail "differs from live although unchanged since the snapshot: $rel"; }
    done < <(find "$WORK" -type f -print0)
fi

DUMP="$WORK$STAGE/dumps/authentik.pgdump"
AK="not tested"
if [ -s "$DUMP" ]; then
    IMG=$(docker inspect -f '{{.Config.Image}}' authentik-postgresql 2>/dev/null)
    PG=restore-test-pg-$$
    if docker run -d --rm --name "$PG" --network none --memory 768m --mount type=tmpfs,destination=/var/lib/postgresql \
        -e POSTGRES_USER=rt -e POSTGRES_DB=rt -e POSTGRES_PASSWORD="$(head -c 18 /dev/urandom | base64)" "${IMG:-postgres:18-alpine}" >/dev/null; then
        for _ in $(seq 60); do docker exec "$PG" pg_isready -h 127.0.0.1 -U rt -q && break; sleep 1; done
        if docker exec -i "$PG" sh -c 'createdb -U rt authentik && pg_restore -U rt -d authentik --no-owner --no-privileges --exit-on-error' < "$DUMP" >/dev/null 2>&1; then
            got=$(docker exec "$PG" psql -U rt -d authentik -At -c "$COUNTS" 2>/dev/null)
            live=$(docker exec authentik-postgresql sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -At -c \"set default_transaction_read_only=on\" -c \"$COUNTS\"" 2>/dev/null | grep '|')
            v() { awk -F'|' -v k="$2" '$1==k{print $2}' <<<"$1"; }
            AK="Users $(v "$got" users)/$(v "$live" users), groups $(v "$got" groups)/$(v "$live" groups), apps $(v "$got" apps)/$(v "$live" apps) (restored/live)"
            [ "$(v "$got" users)" -gt 0 ] 2>/dev/null || fail "Authentik restore has no users"
        else
            fail "Authentik dump did not restore"
        fi
    else
        fail "Authentik throwaway postgres did not start"
    fi
    docker rm -f "$PG" >/dev/null 2>&1; PG=""
else
    fail "Authentik dump missing"
fi

[ ${#FAILS[@]} -eq 0 ] && STATUS=1 || STATUS=0
MB=$((BYTES/1048576))
if [ "$STATUS" = 1 ]; then head="✅ <b>Backup restore test OK</b>"; else head="❌ <b>Backup restore test FAILED</b>"; fi
msg="$head

• Snapshot ${SID:-none}, $((AGE/3600)) h old
• restic check 5%: $([[ " ${FAILS[*]} " == *"restic check"* ]] && echo failed || echo ok)
• Restored ${MB} MiB in ${RSECS} s
• SQLite dumps: $NDB checked
• Files compared with live: $NCMP, unexpected differences: $NDIFF
• Authentik: $(esc "$AK")"
for n in "${NOTES[@]}"; do msg+="
• ⚠️ $n"; done
for f in "${FAILS[@]}"; do msg+="
• ❌ $f"; done
"$OOB" "$msg" >/dev/null || log "Telegram summary not sent"
log "finished status=$STATUS fails=${#FAILS[@]}"
[ "$STATUS" = 1 ]
