#!/usr/bin/env bash
# Runs beefy-repo-maint.sh against a fake restic. Usage: ./test_beefy_repo_maint.sh
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }

mkdir -p "$T/bin" "$T/repo"
cat > "$T/bin/restic" <<'STUB'
#!/usr/bin/env bash
echo "restic $*" >> "$FAKE_LOG"
case " $* " in
  *" forget "*) exit "${FAKE_FORGET_RC:-0}" ;;
  *" prune "*) exit "${FAKE_PRUNE_RC:-0}" ;;
  *" check "*) exit "${FAKE_CHECK_RC:-0}" ;;
  *" snapshots "*)
    [[ -n ${FAKE_EMPTY:-} ]] && { echo '[]'; exit 0; }
    echo '[{"time":"2026-10-29T04:26:10.5+01:00","short_id":"aa","summary":{"total_bytes_processed":2000}},{"time":"2026-10-28T04:26:00+01:00","short_id":"bb","summary":{"total_bytes_processed":1000}}]' ;;
  *) exit 1 ;;
esac
STUB
cat > "$T/bin/chown" <<'STUB'
#!/usr/bin/env bash
echo "chown $*" >> "$FAKE_LOG"
STUB
chmod +x "$T/bin/restic" "$T/bin/chown"
head -c 5000 /dev/zero > "$T/repo/pack"

S="$HERE/beefy-repo-maint.sh"
run() {
    rm -f "$T/log" "$T/prom"
    env PATH="$T/bin:$PATH" FAKE_LOG="$T/log" REPO="$T/repo" PROM="$T/prom" RESTIC_PASSWORD_FILE=/dev/null "$@" "$S" > "$T/out" 2>&1
}
m() { awk -v k="$1" '$1==k{print $2}' "$T/prom"; }

run DOW=4; rc=$?
[[ $rc == 0 && $(m beefy_backup_maint_last_status) == 1 ]] && ok "weekday run passes" || bad "weekday run passes" "rc=$rc $(cat "$T/out")"
grep -q "forget --host beefy --keep-daily 7 --keep-weekly 4 --keep-monthly 6" "$T/log" && ok "retention 7d/4w/6m for beefy" || bad "retention 7d/4w/6m for beefy" "$(cat "$T/log")"
grep -q -- "--retry-lock" "$T/log" && ok "waits for a running backup's lock" || bad "waits for a running backup's lock"
! grep -q " prune" "$T/log" && ! grep -q " check" "$T/log" && ok "no prune or check on Thursday" || bad "no prune or check on Thursday"
[[ $(m beefy_backup_last_snapshot_timestamp_seconds) == $(date -d 2026-10-29T04:26:10+01:00 +%s) ]] && ok "newest snapshot time in metric" || bad "newest snapshot time in metric" "$(cat "$T/prom")"
[[ $(m beefy_backup_last_snapshot_bytes) == 2000 && $(m beefy_backup_snapshots) == 2 ]] && ok "snapshot size and count" || bad "snapshot size and count" "$(cat "$T/prom")"
[[ $(m beefy_backup_repo_bytes) -ge 5000 ]] && ok "repo size" || bad "repo size" "$(cat "$T/prom")"
grep -q "chown -R beefy-backup:beefy-backup $T/repo" "$T/log" && ok "repo handed back to the REST server user" || bad "repo handed back to the REST server user" "$(cat "$T/log")"

run DOW=7
grep -q " prune" "$T/log" && ok "prune on Sunday" || bad "prune on Sunday"
run DOW=3
grep -q "check --read-data-subset=1/10" "$T/log" && ok "check 10 % on Wednesday" || bad "check 10 % on Wednesday"

run DOW=7 FAKE_PRUNE_RC=1; rc=$?
[[ $rc != 0 && $(m beefy_backup_maint_last_status) == 0 ]] && ok "failed prune is status 0" || bad "failed prune is status 0" "rc=$rc"
run DOW=4 FAKE_FORGET_RC=1
[[ $(m beefy_backup_maint_last_status) == 0 && -n $(m beefy_backup_last_snapshot_timestamp_seconds) ]] && ok "failed forget still reports the snapshot age" || bad "failed forget still reports the snapshot age"

run DOW=4 FAKE_EMPTY=1
[[ $(m beefy_backup_maint_last_status) == 0 && $(m beefy_backup_last_snapshot_timestamp_seconds) == 0 ]] && ok "empty repo is a failure" || bad "empty repo is a failure" "$(cat "$T/prom")"

echo "passed $PASS, failed $FAIL"
[[ $FAIL == 0 ]]
