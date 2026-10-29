#!/usr/bin/env bash
# Runs restore-test.sh against fake restic, docker and Telegram. Usage: ./test_restore_test.sh
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }

mkdir -p "$T/bin"
cat > "$T/bin/restic" <<'STUB'
#!/usr/bin/env bash
args=" $* "
case "$args" in
  *" check "*) echo "check $*" >> "$FAKE_LOG"; exit "${FAKE_CHECK_RC:-0}" ;;
  *" snapshots "*) echo '[{"time":"2026-10-28T04:06:06.1+01:00","short_id":"885b536e"}]' ;;
  *" restore "*)
    t=$(sed -E 's/.*--target ([^ ]+).*/\1/' <<<"$*")
    cp -a "$FAKE_SNAP/." "$t/" ;;
  *) exit 1 ;;
esac
STUB
cat > "$T/bin/docker" <<'STUB'
#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
case "$1" in
  inspect) echo "postgres:18.6-alpine" ;;
  run) echo "cid" ;;
  rm) ;;
  exec)
    case "$*" in
      *pg_isready*) [[ $* == *"-h 127.0.0.1"* ]] && touch "$FAKE_READY"; [[ $* == *"-h 127.0.0.1"* ]] ;;
      *pg_restore*) cat > /dev/null; [[ -e $FAKE_READY ]] || exit 1; exit "${FAKE_PGR_RC:-0}" ;;
      *authentik-postgresql*) printf '%s\n' "${FAKE_LIVE:-users|8}" "groups|10" "apps|35" ;;
      *) printf '%s\n' "${FAKE_RESTORED:-users|8}" "groups|10" "apps|35" ;;
    esac ;;
esac
STUB
cat > "$T/bin/oob" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" > "$FAKE_MSG"
STUB
chmod +x "$T/bin/"*

S="$HERE/restore-test.sh"
OLD=2026-10-27T12:00:00
NEW=2026-10-29T00:30:00

setup() {
    rm -rf "$T/snap" "$T/live" "$T/work" "$T/msg" "$T/log" "$T/prom" "$T/ready"
    mkdir -p "$T/snap/var/lib/fastpi-backup-staging/dumps" "$T/snap/var/lib/fastpi-backup-staging/sqlite/data" "$T/snap/etc/ssh" "$T/live/etc/ssh" "$T/work"
    echo dump > "$T/snap/var/lib/fastpi-backup-staging/dumps/authentik.pgdump"
    sqlite3 "$T/snap/var/lib/fastpi-backup-staging/sqlite/data/app.db" "create table t(x); insert into t values (1);"
    echo "Port 22" > "$T/snap/etc/ssh/sshd_config"
    echo "Port 22" > "$T/live/etc/ssh/sshd_config"
    touch -d "$OLD" "$T/live/etc/ssh/sshd_config"
    touch "$T/up"
}
run() {
    env PATH="$T/bin:$PATH" FAKE_LOG="$T/log" FAKE_MSG="$T/msg" FAKE_SNAP="$T/snap" FAKE_READY="$T/ready" \
        WORK_BASE="$T/work" PROM="$T/prom" OOB="$T/bin/oob" LIVE_ROOT="$T/live" \
        BEEFY_TCP="$T/up" LOCK="$T/lock" NOW="$(date -d 2026-10-29T04:33:00 +%s)" "$@" "$S" > "$T/out" 2>&1
}
status() { awk '/^backup_restore_test_last_status /{print $2}' "$T/prom"; }

setup; run; rc=$?
[[ $rc == 0 && $(status) == 1 ]] && ok "healthy backup passes" || bad "healthy backup passes" "rc=$rc status=$(status) $(cat "$T/out")"
grep -q "read-data-subset=5%" "$T/log" && ok "restic check reads 5% of the data" || bad "restic check reads 5% of the data"
grep -q "✅" "$T/msg" && grep -q "Users 8/8" "$T/msg" && ok "Telegram summary ok with Authentik counts" || bad "Telegram summary ok with Authentik counts" "$(cat "$T/msg")"
[[ -z $(ls -A "$T/work") ]] && ok "scratch dir removed" || bad "scratch dir removed"
grep -q "docker rm -f" "$T/log" && ok "throwaway postgres removed" || bad "throwaway postgres removed"
grep -q -- "--network none" "$T/log" && ok "throwaway postgres has no network" || bad "throwaway postgres has no network"
grep -q "pg_isready -h 127.0.0.1" "$T/log" && ok "waits for the real server, not the init server on the socket" || bad "waits for the real server, not the init server on the socket"
grep -q "backup_restore_test_snapshot_age_seconds 8" "$T/prom" && ok "snapshot age in metric" || bad "snapshot age in metric" "$(cat "$T/prom")"

setup; run FAKE_CHECK_RC=1
[[ $(status) == 0 ]] && grep -q "restic check" "$T/msg" && ok "failed restic check reported" || bad "failed restic check reported" "$(cat "$T/msg")"

setup; echo garbage > "$T/snap/var/lib/fastpi-backup-staging/sqlite/data/app.db"; run
[[ $(status) == 0 ]] && grep -q "app.db" "$T/msg" && ok "corrupt SQLite dump reported" || bad "corrupt SQLite dump reported" "$(cat "$T/msg")"

setup; echo "Port 2222" > "$T/live/etc/ssh/sshd_config"; touch -d "$OLD" "$T/live/etc/ssh/sshd_config"; run
[[ $(status) == 0 ]] && grep -q "sshd_config" "$T/msg" && ok "file unchanged since the snapshot but different reported" || bad "file unchanged since the snapshot but different reported" "$(cat "$T/msg")"

setup; echo "Port 2222" > "$T/live/etc/ssh/sshd_config"; touch -d "$NEW" "$T/live/etc/ssh/sshd_config"; run
[[ $(status) == 1 ]] && ok "file edited after the snapshot is not a failure" || bad "file edited after the snapshot is not a failure" "$(cat "$T/msg")"

setup; run FAKE_PGR_RC=1
[[ $(status) == 0 ]] && grep -q "Authentik" "$T/msg" && ok "failed Authentik restore reported" || bad "failed Authentik restore reported" "$(cat "$T/msg")"
grep -q "docker rm -f" "$T/log" && ok "throwaway postgres removed after a failure" || bad "throwaway postgres removed after a failure"

setup; run FAKE_RESTORED="users|0"
[[ $(status) == 0 ]] && ok "empty restored user table is a failure" || bad "empty restored user table is a failure"

setup; rm "$T/up"; run
[[ $(status) == 2 && ! -s $T/msg ]] && ok "beefy asleep: skipped, no message" || bad "beefy asleep: skipped, no message" "status=$(status)"

echo "passed $PASS, failed $FAIL"
[[ $FAIL == 0 ]]
