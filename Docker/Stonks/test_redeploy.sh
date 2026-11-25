#!/usr/bin/env bash
# Tests the pre-deploy DB backup of redeploy.sh in a throwaway copy (no build, no deploy).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
pass=0; fail=0
ok() { echo "ok   $1"; pass=$((pass+1)); }
ko() { echo "FAIL $1"; fail=$((fail+1)); }
setup() {
  T=$(mktemp -d); mkdir -p "$T/deploy/data/backups" "$T/code"
  cp "$HERE/redeploy.sh" "$T/deploy/"
  sqlite3 "$T/deploy/data/stonks.db" 'create table t(x); insert into t values (42);'
}
run() { STONKS_CODE_DIR="$T/code" RUST_BUILD_LOCK="$T/lock" bash "$T/deploy/redeploy.sh" >"$T/out" 2>&1; echo $?; }

setup
rc=$(run)
n=$(ls "$T/deploy/data/backups"/stonks-*.db 2>/dev/null | wc -l)
[ "$n" = 1 ] && [ "$(sqlite3 "$T"/deploy/data/backups/stonks-*.db 'select x from t')" = 42 ] && ok "writable: backup holds the data" || ko "writable: backup holds the data ($n files)"
grep -q "Building" "$T/out" && ok "writable: goes on to build" || ko "writable: goes on to build"
rm -rf "$T"

setup
chmod 555 "$T/deploy/data/backups"
rc=$(run)
[ "$rc" != 0 ] && ok "unwritable: exits non-zero" || ko "unwritable: exits non-zero (rc=$rc)"
grep -q "Building" "$T/out" && ko "unwritable: stops before build" || ok "unwritable: stops before build"
grep -q "backup failed" "$T/out" && ok "unwritable: says backup failed" || ko "unwritable: says backup failed"
chmod 755 "$T/deploy/data/backups"; rm -rf "$T"

setup
rm "$T/deploy/data/stonks.db"
rc=$(run)
grep -q "Building" "$T/out" && ok "no DB yet: goes on" || ko "no DB yet: goes on"
rm -rf "$T"

echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
