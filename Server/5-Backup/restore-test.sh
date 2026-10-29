#!/usr/bin/env bash
# Monthly restore test of both restic repos: fastpi's on beefy (check, restore, SQLite, live compare, Authentik) and beefy's on fastpi (check, restore sample, SQLite, DT5 dump, KEK). Telegram summary. Runs as root from fastpi-restore-test.service; never touches live data.
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
BREPO=${BREPO:-/var/lib/beefy-backup/beefy}
BPASS=${BPASS:-/root/.config/restic/beefy-repo.pass}
BSTAGE=/var/lib/beefy-backup-staging
BINCLUDES=(
    "$BSTAGE"
    /etc/fstab
    /home/buntu/Projects/Docker/docker-compose.yaml
    /srv/appdata/jellyfin/data/plugins/configurations
    /srv/appdata/dt5/.dependency-track/keys
)
BEXPECT=(seerr/db/db.sqlite3 jellyfin/data/data/jellyfin.db radarr/radarr.db sonarr/sonarr.db)
KEK=/srv/appdata/dt5/.dependency-track/keys/secret-management-kek.json
COUNTS="select 'users', count(*) from authentik_core_user union all select 'groups', count(*) from authentik_core_group union all select 'apps', count(*) from authentik_core_application"

R() { restic -o sftp.command="$SSHC" "$@"; }
# read-only and lock-free: root-owned lock files would be unreadable for rest-server (user beefy-backup) and fail a concurrent beefy backup
RB() { restic -r "$BREPO" --password-file "$BPASS" --no-lock "$@"; }
log() { echo "restore-test: $*"; }
esc() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' <<<"$*"; }

START=$(date +%s)
STATUS=0 AGE=0 BYTES=0 RSECS=0 BSTATUS=0 BAGE=0 FASTPI_RUN=1 NDB=0 NCMP=0 NDIFF=0
FAILS=() NOTES=()
WORK="" PG=""
fail() { FAILS+=("$(esc "$*")"); log "FAIL $*"; }
note() { NOTES+=("$(esc "$*")"); log "$*"; }

write_metric() {
    local now ok; now=$(date +%s)
    ok=$(grep -s '^backup_restore_test_last_success_timestamp_seconds ' "$PROM" | awk '{print $2}')
    [ "$STATUS" = 1 ] && ok=$now
    cat > "$PROM.tmp" <<EOM
# TYPE backup_restore_test_last_run_timestamp_seconds gauge
backup_restore_test_last_run_timestamp_seconds $now
# TYPE backup_restore_test_last_status gauge
# 1 ok, 0 failed, 2 skipped (beefy asleep)
backup_restore_test_last_status $STATUS
# TYPE backup_restore_test_last_success_timestamp_seconds gauge
backup_restore_test_last_success_timestamp_seconds ${ok:-0}
# TYPE backup_restore_test_beefy_status gauge
# beefy's repo on fastpi: 1 ok, 0 failed
backup_restore_test_beefy_status $BSTATUS
# TYPE backup_restore_test_beefy_snapshot_age_seconds gauge
backup_restore_test_beefy_snapshot_age_seconds $BAGE
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

umask 077
WORK=$(mktemp -d "$WORK_BASE/fastpi-restore-test.XXXXXX")

fastpi_part() {
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
}

beefy_part() {
    local before=${#FAILS[@]} snap bt db r rel n
    RB check --read-data-subset=5% >/dev/null 2>&1 || fail "beefy restic check --read-data-subset=5% failed"
    snap=$(RB snapshots latest --tag nightly --host beefy --json 2>/dev/null)
    BSID=$(jq -r '.[0].short_id // empty' <<<"$snap" 2>/dev/null)
    bt=$(jq -r '.[0].time // empty' <<<"$snap" 2>/dev/null)
    if [ -z "$bt" ]; then fail "no beefy snapshot found"; BSTATUS=0; return; fi
    BAGE=$(( ${NOW:-$(date +%s)} - $(date -d "$bt" +%s) ))
    [ "$BAGE" -gt $((48*3600)) ] && note "latest beefy snapshot is $((BAGE/3600)) h old"
    local inc=(); for p in "${BINCLUDES[@]}"; do inc+=(--include "$p"); done
    mkdir -p "$WORK/beefy"
    RB restore "$BSID" --target "$WORK/beefy" "${inc[@]}" >/dev/null 2>&1 || fail "beefy restic restore failed"
    local B="$WORK/beefy$BSTAGE"
    NBDB=0
    while IFS= read -r -d '' db; do
        NBDB=$((NBDB+1))
        r=$(sqlite3 -readonly "$db" "pragma quick_check" 2>&1 | head -1)
        [ "$r" = ok ] || fail "beefy SQLite ${db#"$B/sqlite"}: $r"
    done < <(find "$B/sqlite" -type f -print0 2>/dev/null)
    for rel in "${BEXPECT[@]}"; do [ -f "$B/sqlite/srv/appdata/$rel" ] || fail "beefy SQLite dump $rel missing"; done
    NDT5=0
    if [ -s "$B/dumps/dt5.pgdump" ]; then
        n=$(docker run --rm -i --network none --memory 256m "${IMG:-postgres:18-alpine}" pg_restore -l < "$B/dumps/dt5.pgdump" 2>/dev/null | grep -vc '^;')
        [ "${n:-0}" -gt 0 ] 2>/dev/null && NDT5=$n || fail "DT5 dump not readable by pg_restore"
    else
        fail "DT5 dump missing"
    fi
    if jq -e '(.primaryKeyId != null) and ((.key // []) | length > 0)' "$WORK/beefy$KEK" >/dev/null 2>&1; then KEKOK=ok; else KEKOK=bad; fail "DT5 KEK invalid or missing"; fi
    [ ${#FAILS[@]} -eq "$before" ] && BSTATUS=1 || BSTATUS=0
    log "beefy snapshot $BSID: $NBDB SQLite dumps, DT5 dump $NDT5 entries, KEK $KEKOK"
}

IMG=$(docker inspect -f '{{.Config.Image}}' authentik-postgresql 2>/dev/null)
if ! timeout 5 bash -c "< $BEEFY_TCP" 2>/dev/null; then
    FASTPI_RUN=0; note "fastpi repo skipped: beefy asleep"
else
    exec 9>"$LOCK"
    if flock -w 300 9; then fastpi_part; else FASTPI_RUN=0; note "fastpi repo skipped: its backup still running"; fi
fi
beefy_part

if [ ${#FAILS[@]} -gt 0 ]; then STATUS=0; elif [ "$FASTPI_RUN" = 0 ]; then STATUS=2; else STATUS=1; fi
MB=$((BYTES/1048576))
case $STATUS in
    1) head="✅ <b>Backup restore test OK</b>" ;;
    2) head="⚠️ <b>Backup restore test: fastpi repo skipped</b>" ;;
    *) head="❌ <b>Backup restore test FAILED</b>" ;;
esac
msg="$head

• Snapshot ${SID:-none}, $((AGE/3600)) h old
• restic check 5%: $([[ " ${FAILS[*]} " == *"restic check"* ]] && echo failed || echo ok)
• Restored ${MB} MiB in ${RSECS} s
• SQLite dumps: $NDB checked
• Files compared with live: $NCMP, unexpected differences: $NDIFF
• Authentik: $(esc "$AK")
• Beefy: snapshot ${BSID:-none}, $((BAGE/3600)) h old; SQLite dumps: ${NBDB:-0} checked; DT5 dump: ${NDT5:-0} entries; KEK ${KEKOK:-bad}"
for n in "${NOTES[@]}"; do msg+="
• ⚠️ $n"; done
for f in "${FAILS[@]}"; do msg+="
• ❌ $f"; done
"$OOB" "$msg" >/dev/null || log "Telegram summary not sent"
log "finished status=$STATUS fails=${#FAILS[@]}"
[ "$STATUS" = 1 ]
