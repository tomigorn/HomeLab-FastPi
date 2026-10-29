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
if [[ $args == *" -r $FAKE_BREPO "* ]]; then
  echo "beefy $*" >> "$FAKE_LOG"
  case "$args" in
    *" check "*) exit "${FAKE_BCHECK_RC:-0}" ;;
    *" snapshots "*) [[ -n ${FAKE_BEMPTY:-} ]] && { echo '[]'; exit 0; }; echo '[{"time":"2026-10-29T04:26:10+01:00","short_id":"beef0001"}]' ;;
    *" restore "*) t=$(sed -E 's/.*--target ([^ ]+).*/\1/' <<<"$*"); cp -a "$FAKE_BSNAP/." "$t/" ;;
    *) exit 1 ;;
  esac
  exit 0
fi
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
  run)
    if [[ $* == *"pg_restore -l"* ]]; then
      grep -q PGDMP || exit 1
      printf '%s\n' "; Archive created" "1; 2615 2200 SCHEMA - public" "2; 1259 16390 TABLE public project"
    else echo "cid"; fi ;;
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
    rm -rf "$T/bsnap"; B="$T/bsnap/var/lib/beefy-backup-staging"
    for d in seerr/db/db.sqlite3 jellyfin/data/data/jellyfin.db radarr/radarr.db sonarr/sonarr.db; do
        mkdir -p "$B/sqlite/srv/appdata/$(dirname "$d")"; sqlite3 "$B/sqlite/srv/appdata/$d" "create table t(x);"
    done
    mkdir -p "$B/dumps" "$T/bsnap/srv/appdata/dt5/.dependency-track/keys"
    printf 'PGDMP fake' > "$B/dumps/dt5.pgdump"
    echo '{"primaryKeyId":1,"key":[{"keyId":1}]}' > "$T/bsnap/srv/appdata/dt5/.dependency-track/keys/secret-management-kek.json"
}
run() {
    env PATH="$T/bin:$PATH" FAKE_BREPO="$T/brepo" FAKE_BSNAP="$T/bsnap" BREPO="$T/brepo" BPASS=/dev/null FAKE_LOG="$T/log" FAKE_MSG="$T/msg" FAKE_SNAP="$T/snap" FAKE_READY="$T/ready" \
        WORK_BASE="$T/work" PROM="$T/prom" OOB="$T/bin/oob" LIVE_ROOT="$T/live" \
        BEEFY_TCP="$T/up" LOCK="$T/lock" NOW="$(date -d 2026-10-29T04:33:00 +%s)" "$@" "$S" > "$T/out" 2>&1
}
status() { awk '/^backup_restore_test_last_status /{print $2}' "$T/prom"; }
metric() { awk -v k="$1" '$1==k{print $2}' "$T/prom"; }

setup; run; rc=$?
[[ $rc == 0 && $(status) == 1 ]] && ok "healthy backup passes" || bad "healthy backup passes" "rc=$rc status=$(status) $(cat "$T/out")"
grep -q "read-data-subset=5%" "$T/log" && ok "restic check reads 5% of the data" || bad "restic check reads 5% of the data"
grep -q "✅" "$T/msg" && grep -q "Users 8/8" "$T/msg" && ok "Telegram summary ok with Authentik counts" || bad "Telegram summary ok with Authentik counts" "$(cat "$T/msg")"
[[ -z $(ls -A "$T/work") ]] && ok "scratch dir removed" || bad "scratch dir removed"
grep -q "docker rm -f" "$T/log" && ok "throwaway postgres removed" || bad "throwaway postgres removed"
grep -q -- "--network none" "$T/log" && ok "throwaway postgres has no network" || bad "throwaway postgres has no network"
grep -q "pg_isready -h 127.0.0.1" "$T/log" && ok "waits for the real server, not the init server on the socket" || bad "waits for the real server, not the init server on the socket"
grep -q "backup_restore_test_snapshot_age_seconds 8" "$T/prom" && ok "snapshot age in metric" || bad "snapshot age in metric" "$(cat "$T/prom")"

grep -q "beefy .*check --read-data-subset=5%" "$T/log" && ok "beefy repo checked 5%" || bad "beefy repo checked 5%"
n=$(grep -c '^beefy ' "$T/log"); [[ $n -ge 3 && $(grep '^beefy ' "$T/log" | grep -c -- '--no-lock') == "$n" ]] && ok "beefy repo read without lock files (rest-server user cannot read root's)" || bad "beefy repo read without lock files" "$(grep '^beefy ' "$T/log")"
grep -q "Beefy: snapshot beef0001" "$T/msg" && grep -q "SQLite dumps: 4" "$T/msg" && ok "Telegram summary covers beefy" || bad "Telegram summary covers beefy" "$(cat "$T/msg")"
grep -q "DT5 dump: 2 entries" "$T/msg" && grep -q "KEK ok" "$T/msg" && ok "DT5 dump listed and KEK valid" || bad "DT5 dump listed and KEK valid" "$(cat "$T/msg")"
[[ $(metric backup_restore_test_beefy_status) == 1 && $(metric backup_restore_test_last_success_timestamp_seconds) -gt 0 ]] && ok "beefy status and last success in metrics" || bad "beefy status and last success in metrics" "$(cat "$T/prom")"

setup; run FAKE_BCHECK_RC=1
[[ $(status) == 0 && $(metric backup_restore_test_beefy_status) == 0 ]] && grep -q "beefy restic check" "$T/msg" && ok "failed beefy repo check reported" || bad "failed beefy repo check reported" "$(cat "$T/msg")"

setup; echo garbage > "$T/bsnap/var/lib/beefy-backup-staging/sqlite/srv/appdata/radarr/radarr.db"; run
[[ $(status) == 0 ]] && grep -q "radarr.db" "$T/msg" && ok "corrupt beefy SQLite dump reported" || bad "corrupt beefy SQLite dump reported" "$(cat "$T/msg")"

setup; rm "$T/bsnap/var/lib/beefy-backup-staging/sqlite/srv/appdata/jellyfin/data/data/jellyfin.db"; run
[[ $(status) == 0 ]] && grep -q "jellyfin.db missing" "$T/msg" && ok "missing Jellyfin dump reported" || bad "missing Jellyfin dump reported" "$(cat "$T/msg")"

setup; echo broken > "$T/bsnap/var/lib/beefy-backup-staging/dumps/dt5.pgdump"; run
[[ $(status) == 0 ]] && grep -q "DT5 dump" "$T/msg" && ok "unreadable DT5 dump reported" || bad "unreadable DT5 dump reported" "$(cat "$T/msg")"

setup; echo '{}' > "$T/bsnap/srv/appdata/dt5/.dependency-track/keys/secret-management-kek.json"; run
[[ $(status) == 0 ]] && grep -q "KEK" "$T/msg" && ok "invalid DT5 KEK reported" || bad "invalid DT5 KEK reported" "$(cat "$T/msg")"

setup; run FAKE_BEMPTY=1
[[ $(status) == 0 ]] && grep -q "no beefy snapshot" "$T/msg" && ok "empty beefy repo reported" || bad "empty beefy repo reported" "$(cat "$T/msg")"

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
[[ $(status) == 2 && $(metric backup_restore_test_beefy_status) == 1 ]] && grep -q "fastpi repo skipped" "$T/msg" && grep -q "Beefy: snapshot" "$T/msg" && ok "beefy asleep: fastpi repo skipped, beefy repo still tested" || bad "beefy asleep: fastpi repo skipped, beefy repo still tested" "status=$(status) b=$(metric backup_restore_test_beefy_status) $(cat "$T/msg") $(cat "$T/out")"

echo "passed $PASS, failed $FAIL"
[[ $FAIL == 0 ]]
