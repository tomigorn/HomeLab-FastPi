#!/usr/bin/env bash
# Runs claude-scratch.sh against temp folders with a fake mount. Usage: ./test_claude_scratch.sh
HERE=$(cd "$(dirname "$0")" && pwd)
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }
mkdir -p "$W/bin"
cat > "$W/bin/mount" <<'F'
#!/bin/sh
echo "$@" > "$FAKE_LOG"; touch "$FAKE_MOUNTED"
F
cat > "$W/bin/mountpoint" <<'F'
#!/bin/sh
[ -e "$FAKE_MOUNTED" ]
F
chmod +x "$W/bin/"*
run() { PATH="$W/bin:$PATH" SCRATCH_SRC="$W/src" SCRATCH_DST="${DST:-$W/dst}" SCRATCH_OWNER="$(id -un)" FAKE_LOG="$W/log" FAKE_MOUNTED="$W/mounted" "$HERE/claude-scratch.sh"; }

mkdir -p "$W/src/-home-pi/s1/tasks" "$W/dst/-home-pi/s0"
echo a > "$W/src/-home-pi/s1/tasks/out"; echo b > "$W/src/top.txt"; echo old > "$W/dst/-home-pi/s0/keep"
run; rc=$?
[[ $rc == 0 ]] && ok "exit 0" || bad "exit 0" "rc=$rc"
[[ $(cat "$W/dst/-home-pi/s1/tasks/out" 2>/dev/null) == a && $(cat "$W/dst/top.txt" 2>/dev/null) == b ]] && ok "moves existing scratch to disk" || bad "moves existing scratch to disk"
[[ -f $W/dst/-home-pi/s0/keep ]] && ok "keeps what is already on disk" || bad "keeps what is already on disk"
[[ -z $(find "$W/src" -mindepth 1 2>/dev/null) && -d $W/src ]] && ok "tmpfs copy emptied, mount point kept" || bad "tmpfs copy emptied" "$(find "$W/src")"
[[ $(cat "$W/log" 2>/dev/null) == "-o bind,nosuid,nodev $W/dst $W/src" ]] && ok "bind-mounts disk folder over the scratch path" || bad "bind mount args" "$(cat "$W/log" 2>/dev/null)"
[[ $(stat -c %a "$W/dst") == 700 ]] && ok "disk folder is 0700" || bad "disk folder is 0700" "$(stat -c %a "$W/dst")"

rm -f "$W/log"; echo c > "$W/src/new"
run; rc=$?
[[ $rc == 0 && ! -e $W/log && -f $W/src/new ]] && ok "already mounted: does nothing" || bad "already mounted: does nothing" "rc=$rc"

rm -rf "$W/src" "$W/dst" "$W/mounted" "$W/log"
run; rc=$?
[[ $rc == 0 && -d $W/src && -d $W/dst && -f $W/log ]] && ok "fresh boot: creates both folders and mounts" || bad "fresh boot" "rc=$rc"

rm -rf "$W/src" "$W/mounted" "$W/log"; mkdir -p "$W/cache"; chmod 600 "$W/cache"
DST="$W/cache/dst" run; rc=$?
[[ $rc == 0 && $(stat -c %a "$W/cache") == 7* && -d $W/cache/dst ]] && ok "untraversable parent made enterable for its owner" || bad "untraversable parent" "rc=$rc mode=$(stat -c %a "$W/cache")"
chmod 700 "$W/cache"

echo "$PASS passed, $FAIL failed"
[[ $FAIL == 0 ]]
