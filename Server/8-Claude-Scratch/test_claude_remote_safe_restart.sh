#!/usr/bin/env bash
# Runs claude-remote-safe-restart against a fake HOME, /proc, cgroup and systemctl. Usage: ./test_claude_remote_safe_restart.sh
HERE=$(cd "$(dirname "$0")" && pwd)
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }
PROM=$W/textfile/claude_remote_restart.prom
CG=$W/cg/user.slice/claude-remote.service

mkdir -p "$W/bin" "$W/textfile" "$CG" "$W/home/.claude/projects/p" "$W/home/.local/share/claude/versions" "$W/home/.local/bin" "$W/proc/100" "$W/proc/200"
cat > "$W/bin/systemctl" <<'F'
#!/bin/sh
case "$*" in
  *MainPID*) echo 100 ;;
  *restart*) echo restart >> "$FAKE_LOG" ;;
esac
F
chmod +x "$W/bin/systemctl"
touch "$W/home/.local/share/claude/versions/2.1.0"
ln -s "$W/home/.local/share/claude/versions/2.1.0" "$W/home/.local/bin/claude"
ln -s "$W/home/.local/share/claude/versions/2.1.0" "$W/proc/100/exe"
echo "0::/user.slice/claude-remote.service" > "$W/proc/100/cgroup"
ln -s /usr/bin/node "$W/proc/200/exe"
printf 'node\0--test\0"x"\\y\0' > "$W/proc/200/cmdline"

run() { PATH="$W/bin:$PATH" HOME="$W/home" PROC_ROOT="$W/proc" CGROUP_ROOT="$W/cg" TEXTFILE="$W/textfile" FAKE_LOG="$W/log" "$HERE/claude-remote-safe-restart" >/dev/null; }
metric() { grep "^claude_remote_restart_$1" "$PROM" 2>/dev/null; }
value() { metric "$1" | awk '{print $NF}'; }

echo 100 > "$CG/cgroup.procs"; rm -f "$W/log"
run; rc=$?
[[ $rc == 0 && $(cat "$W/log" 2>/dev/null) == restart ]] && ok "idle: restarts" || bad "idle: restarts" "rc=$rc"
[[ $(value deferred_since_timestamp_seconds) == 0 ]] && ok "idle: deferred_since is 0" || bad "idle: deferred_since is 0" "$(metric deferred_since)"
[[ $(value last_run_timestamp_seconds) -gt $(( $(date +%s) - 60 )) ]] && ok "writes last_run" || bad "writes last_run" "$(metric last_run)"

printf '100\n200\n' > "$CG/cgroup.procs"; rm -f "$W/log"
run; rc=$?
[[ $rc == 75 && ! -e $W/log ]] && ok "tool process: deferred, no restart" || bad "tool process: deferred" "rc=$rc"
since=$(value deferred_since_timestamp_seconds)
[[ $since -gt $(( $(date +%s) - 60 )) ]] && ok "first deferral: deferred_since is now" || bad "first deferral: deferred_since is now" "$since"
metric deferred_since | grep -q 'reason="processes",blocker="node --test \\"x\\"\\\\y"' && ok "names the blocking process, escaped" || bad "names the blocking process" "$(metric deferred_since)"

sed -i "s/ $since\$/ 1000/" "$PROM"
run; rc=$?
[[ $rc == 75 && $(value deferred_since_timestamp_seconds) == 1000 ]] && ok "later deferral keeps when it started" || bad "later deferral keeps start" "$(metric deferred_since)"

echo 100 > "$CG/cgroup.procs"; touch "$W/home/.claude/projects/p/s.jsonl"
run; rc=$?
[[ $rc == 75 && $(value deferred_since_timestamp_seconds) == 1000 ]] && metric deferred_since | grep -q 'reason="sessions"' && ok "active session: deferred, start kept" || bad "active session: deferred" "$(metric deferred_since)"

touch -d '2 hours ago' "$W/home/.claude/projects/p/s.jsonl"; rm -f "$W/log"
run; rc=$?
[[ $rc == 0 && $(cat "$W/log" 2>/dev/null) == restart && $(value deferred_since_timestamp_seconds) == 0 ]] && ok "idle again: restarts and clears deferred_since" || bad "idle again" "rc=$rc $(metric deferred_since)"

rm -f "$PROM" "$W/log"
DRY_RUN=1 run; rc=$?
[[ $rc == 0 && ! -e $W/log && ! -e $PROM ]] && ok "DRY_RUN: no restart, no metrics" || bad "DRY_RUN" "rc=$rc"

echo "$PASS passed, $FAIL failed"
[[ $FAIL == 0 ]]
