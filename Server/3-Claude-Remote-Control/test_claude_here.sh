#!/usr/bin/env bash
# Runs claude-here against a fake HOME, systemctl, clock and cgroup tree. Usage: ./test_claude_here.sh
HERE=$(cd "$(dirname "$0")" && pwd)
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }
check() { local name=$1; shift; if "$@"; then ok "$name"; else bad "$name" "$OUT"; fi; }

H=$W/home
mkdir -p "$W/bin" "$W/fake/since" "$W/cg" "$H/Projects" "$H/landingpage" "$H/notes" "$H/batch" "$H/Documents/development/WG-Chores" "$H/HomeLab-Unraid-Tower" "$H/secret" "$H/.claude/projects" "$H/.local/share/claude/versions"
ln -s "$H/secret" "$H/Projects/sneaky"
mkdir -p "$H/Documents/development/Fresh" "$H/Documents/development/Known"
git init -q "$H/Documents/development/Fresh"; git init -q "$H/Documents/development/Known"
printf '{"projects": {"%s": {"hasTrustDialogAccepted": true}, "%s": {"hasTrustDialogAccepted": true}}}' "$H" "$H/Documents/development/Known" > "$H/.claude.json"
ln -s "$H/secret" "$H/Documents/development/evil"
cat > "$W/allowlist" <<'F'
# comment
~/Projects
~/landingpage
~/notes
~/batch
~/Documents/development/*
~/HomeLab-Unraid-Tower
F
touch "$W/fake/units"
cat > "$W/bin/systemctl" <<'F'
#!/usr/bin/env bash
[[ $1 == --user ]] && shift
U=$FAKE/units
case $1 in
  list-units) [[ $* == *activating* ]] || exit 0; cat "$U" ;;
  is-active) grep -qxF -- "${!#}" "$U" ;;
  start) echo "start $2" >> "$FAKE/log"; grep -qxF -- "$2" "$U" || echo "$2" >> "$U" ;;
  stop) echo "stop $2" >> "$FAKE/log"; grep -vxF -- "$2" "$U" > "$U.n"; mv "$U.n" "$U" ;;
  show)
    unit=${!#}
    case "$*" in
      *ActiveEnterTimestamp*) cat "$FAKE/since/$unit" 2>/dev/null || echo "Wed 2026-11-25 08:00:00 CET" ;;
      *ControlGroup*) echo "/app.slice/$unit" ;;
      *NRestarts*) cat "$FAKE/restarts" 2>/dev/null || echo 0 ;;
    esac ;;
esac
F
chmod +x "$W/bin/systemctl"
cat > "$W/bin/hostname" <<'F'
#!/bin/sh
echo fastpi
F
chmod +x "$W/bin/hostname"

ch() { OUT=$(CLAUDE_HERE_WAIT=0 PATH="$W/bin:$PATH" HOME="$H" FAKE="$W/fake" CLAUDE_HERE_ALLOWLIST="$W/allowlist" CLAUDE_HERE_STATE="$W/state" CGROUP_ROOT="$W/cg" PROC_ROOT="$W/proc" CLAUDE_HERE_NOW="${NOW:-}" "$HERE/claude-here" "$@" 2>&1); RC=$?; }
unit() { echo "claude-remote@$(systemd-escape "$1").service"; }
log_has() { grep -qxF -- "$1" "$W/fake/log" 2>/dev/null; }
clear_log() { rm -f "$W/fake/log"; }
running() { grep -qxF -- "$1" "$W/fake/units"; }
add_running() { echo "$1" >> "$W/fake/units"; mkdir -p "$W/cg/app.slice/$1"; : > "$W/cg/app.slice/$1/cgroup.procs"; }
reset_units() { : > "$W/fake/units"; rm -f "$W/fake/since/"*; rm -rf "$W/state"; clear_log; }

echo "help"
ch --help; if [ $RC = 0 ] && grep -q 'claude-here <folder>' <<<"$OUT"; then ok "--help exits 0 and shows usage"; else bad "--help" "$OUT"; fi
ch; check "no args: usage, exit 2" [ $RC = 2 ]
ch --bogus; check "unknown option: exit 2 with hint" grep -q 'claude-here --help' <<<"$OUT"

echo "trust"
ch "$H/Documents/development/Fresh"; if [ $RC = 1 ] && grep -q 'not trusted' <<<"$OUT" && grep -q 'hasTrustDialogAccepted' <<<"$OUT"; then ok "untrusted repo: refused with how to trust it"; else bad "untrusted repo" "$OUT"; fi
check "untrusted repo: nothing started" [ ! -e "$W/fake/log" ]
ch "$H/Documents/development/Known"; check "trusted repo root: started" [ $RC = 0 ]
ch "$H/Documents/development/Known" batch; check "trusted repo root, batch: started" [ $RC = 0 ]
: > "$W/fake/units"; rm -f "$W/fake/log"

echo "start check"
: > "$W/fake/units"; echo 2 > "$W/fake/restarts"
ch "$H/notes"; if [ $RC = 1 ] && grep -q 'journalctl' <<<"$OUT"; then ok "crash-looping start: exit 1 with the log command"; else bad "crash-looping start" "$OUT"; fi
check "crash-looping start is stopped again" log_has "stop $(unit "auto:$H/notes")"
rm -f "$W/fake/restarts" "$W/fake/log"; : > "$W/fake/units"

echo "allowlist"
ch "$H/secret"; check "outside the allowlist: refused" [ $RC = 1 ]
grep -q 'not in the allowlist' <<<"$OUT" && ok "refusal names the allowlist" || bad "refusal names the allowlist" "$OUT"
ch "$H/Projects/sneaky"; check "symlink into a disallowed folder: refused" [ $RC = 1 ]
ch "$H/Documents/development/evil"; check "symlink under a glob entry: refused" [ $RC = 1 ]
ch "$H/Projects/../secret"; check "dot-dot out of an allowed folder: refused" [ $RC = 1 ]
ch "$H/nope"; check "missing folder: refused" [ $RC = 1 ]
ch "$H"; if [ $RC = 1 ] && grep -q 'always on' <<<"$OUT"; then ok "home: refused with the always-on hint"; else bad "home: refused with the always-on hint" "$OUT"; fi
ch "$H/landingpage" turbo; check "unknown mode: exit 2" [ $RC = 2 ]

echo "start"
reset_units
ch "$H/landingpage"
check "start in an allowed folder: exit 0" [ $RC = 0 ]
check "starts the auto instance" log_has "start $(unit "auto:$H/landingpage")"
grep -q 'fastpi-landingpage' <<<"$OUT" && ok "prints the session name" || bad "prints the session name" "$OUT"
grep -q 'claude-here --stop' <<<"$OUT" && ok "prints the next command" || bad "prints the next command" "$OUT"
clear_log; ch "$H/landingpage/"
check "already running: no second start" [ $RC = 0 -a ! -e "$W/fake/log" ]
ch "$H/Documents/development/WG-Chores" batch
check "glob entry + batch mode" log_has "start $(unit "batch:$H/Documents/development/WG-Chores")"
grep -q 'fastpi-WG-Chores-batch' <<<"$OUT" && ok "batch name gets -batch" || bad "batch name gets -batch" "$OUT"
PATH="$W/bin:$PATH" HOME="$H" FAKE="$W/fake" CLAUDE_HERE_ALLOWLIST="$W/allowlist" CLAUDE_HERE_STATE="$W/state" bash -c "cd '$H/notes' && '$HERE/claude-here' ." >/dev/null 2>&1
check "relative path starts the right instance" log_has "start $(unit "auto:$H/notes")"

echo "exec (what the unit runs)"
cat > "$W/bin/fakeclaude" <<'F'
#!/bin/sh
echo "pwd=$(pwd) args=$*"
F
chmod +x "$W/bin/fakeclaude"
ex() { OUT=$(PATH="$W/bin:$PATH" HOME="$H" CLAUDE_BIN="$W/bin/fakeclaude" CLAUDE_HERE_ALLOWLIST="$W/allowlist" CLAUDE_HERE_STATE="$W/state" CLAUDE_HERE_SETTINGS="$W/batch-settings.json" "$HERE/claude-here" --exec "$1" 2>&1); RC=$?; }
ex "batch:$H/Projects"; check "exec batch without the settings file: refused" [ $RC = 1 ]
cp "$HERE/batch-settings.json" "$W/batch-settings.json"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if "AskUserQuestion" in d["permissions"]["deny"] else 1)' "$W/batch-settings.json"; RC=$?
check "batch settings deny AskUserQuestion" [ $RC = 0 ]
ex "auto:$H/landingpage"
check "exec auto: cwd + name + mode" grep -qF "pwd=$H/landingpage args=remote-control --name fastpi-landingpage --permission-mode auto" <<<"$OUT"
ex "batch:$H/Projects"
check "exec batch: bypass + settings" grep -qF "args=remote-control --name fastpi-Projects-batch --permission-mode bypassPermissions --settings $W/batch-settings.json" <<<"$OUT"
ex "auto:$H"; check "exec home instance keeps the name fastpi" grep -qF "pwd=$H args=remote-control --name fastpi --permission-mode auto" <<<"$OUT"
ex "batch:$H/batch"; check "exec batch instance keeps the name fastpi-batch" grep -qF "args=remote-control --name fastpi-batch --permission-mode bypassPermissions" <<<"$OUT"
ex "batch:$H/secret"; check "exec outside the allowlist: refused" [ $RC = 1 ]
mkdir -p "$W/state/done"; touch "$W/state/done/$(unit "batch:$H/Projects")"
ex "batch:$H/Projects"; check "exec clears an old done marker" [ ! -e "$W/state/done/$(unit "batch:$H/Projects")" ]

echo "list"
reset_units
add_running "$(unit "auto:$H")"
add_running "$(unit "auto:$H/landingpage")"
echo "Wed 2026-11-25 07:00:00 CET" > "$W/fake/since/$(unit "auto:$H/landingpage")"
mkdir -p "$H/.claude/projects/$(sed 's/[^A-Za-z0-9]/-/g' <<<"$H/landingpage")"
NOW=$(date -d '2026-11-25 10:00' +%s)
touch -d '2026-11-25 09:30' "$H/.claude/projects/$(sed 's/[^A-Za-z0-9]/-/g' <<<"$H/landingpage")/s.jsonl"
ch --list
check "list shows both" [ "$(grep -c 'fastpi' <<<"$OUT")" -ge 2 ]
grep 'fastpi-landingpage' <<<"$OUT" | grep -q '30m' && ok "list shows idle from the newest transcript" || bad "list idle" "$OUT"
grep 'fastpi-landingpage' <<<"$OUT" | grep -q '07:00' && ok "list shows since" || bad "list since" "$OUT"
grep -E '^fastpi ' <<<"$OUT" | grep -q 'always on' && ok "list marks always-on" || bad "list marks always-on" "$OUT"
NOW=

echo "stop"
reset_units
add_running "$(unit "auto:$H")"; add_running "$(unit "batch:$H/batch")"; add_running "$(unit "auto:$H/landingpage")"; add_running "$(unit "batch:$H/landingpage")"
ch --stop fastpi; if [ $RC = 1 ] && running "$(unit "auto:$H")"; then ok "stop fastpi: refused"; else bad "stop fastpi: refused" "$OUT"; fi
ch --stop "$H/batch"; if [ $RC = 1 ] && running "$(unit "batch:$H/batch")"; then ok "stop ~/batch: refused"; else bad "stop ~/batch: refused" "$OUT"; fi
grep -q 'always on' <<<"$OUT" && ok "refusal explains always-on" || bad "refusal explains always-on" "$OUT"
ch --stop landingpage; if [ $RC = 1 ] && grep -q 'fastpi-landingpage-batch' <<<"$OUT"; then ok "ambiguous folder: refused, lists names"; else bad "ambiguous folder: refused, lists names" "$OUT"; fi
ch --stop fastpi-landingpage-batch; if [ $RC = 0 ] && ! running "$(unit "batch:$H/landingpage")"; then ok "stop by session name"; else bad "stop by session name" "$OUT"; fi
ch --stop landingpage; if [ $RC = 0 ] && ! running "$(unit "auto:$H/landingpage")"; then ok "stop by folder name"; else bad "stop by folder name" "$OUT"; fi
ch --stop landingpage; if [ $RC = 1 ] && grep -q 'claude-here --list' <<<"$OUT"; then ok "stop when not running: exit 1 with --list hint"; else bad "stop when not running: exit 1 with --list hint" "$OUT"; fi

echo "done marker"
mkdir -p "$W/proc/self"
printf '0::/user.slice/app.slice/%s\n' "$(unit "batch:$H/Projects")" > "$W/proc/self/cgroup"
ch --done; check "done writes the marker for its own instance" [ $RC = 0 -a -e "$W/state/done/$(unit "batch:$H/Projects")" ]
printf '0::/user.slice/app.slice/%s\n' "$(unit "batch:$H/batch")" > "$W/proc/self/cgroup"
ch --done; check "done in the always-on batch: no marker" [ $RC = 0 -a ! -e "$W/state/done/$(unit "batch:$H/batch")" ]
printf '0::/user.slice/app.slice/other.service\n' > "$W/proc/self/cgroup"
ch --done; check "done outside an instance: exit 1" [ $RC = 1 ]

echo "reap"
reset_units
A=$(unit "auto:$H/landingpage"); B=$(unit "batch:$H/Projects"); B2=$(unit "batch:$H/notes"); HOMEU=$(unit "auto:$H"); BATCHU=$(unit "batch:$H/batch")
for u in "$A" "$B" "$B2" "$HOMEU" "$BATCHU"; do add_running "$u"; echo "Tue 2026-11-24 22:00:00 CET" > "$W/fake/since/$u"; done
LP=$H/.claude/projects/$(sed 's/[^A-Za-z0-9]/-/g' <<<"$H/landingpage")
mkdir -p "$LP/s1/subagents"; rm -f "$LP"/*.jsonl
touch -d '2026-11-25 01:00' "$LP/s1/subagents/a.jsonl"
NOW=$(date -d '2026-11-25 08:59' +%s) ch --reap
check "reap at 08:59: idle 7h59 auto kept" running "$A"
check "reap at 08:59: batch before 10:00 kept" running "$B"
check "always-on kept" running "$HOMEU"
NOW=$(date -d '2026-11-25 09:01' +%s) ch --reap
check "reap at 09:01: idle 8h01 auto stopped" bash -c "! grep -qxF -- '$A' '$W/fake/units'"
mkdir -p "$W/state/done"; touch "$W/state/done/$B2"
NOW=$(date -d '2026-11-25 09:02' +%s) ch --reap
check "batch with done marker stopped" bash -c "! grep -qxF -- '$B2' '$W/fake/units'"
check "batch without marker kept before 10:00" running "$B"
NOW=$(date -d '2026-11-25 10:00' +%s) ch --reap
check "batch stopped at 10:00" bash -c "! grep -qxF -- '$B' '$W/fake/units'"
check "always-on home survives everything" running "$HOMEU"
check "always-on batch survives everything" running "$BATCHU"
reset_units; add_running "$A"; echo "Wed 2026-11-25 00:00:00 CET" > "$W/fake/since/$A"
echo 4242 > "$W/cg/app.slice/$A/cgroup.procs"; mkdir -p "$W/proc/4242"; ln -sfn /usr/bin/sleep "$W/proc/4242/exe"
NOW=$(date -d '2026-11-25 12:00' +%s) ch --reap
check "idle auto with a running tool process kept" running "$A"
: > "$W/cg/app.slice/$A/cgroup.procs"
add_running "$B"; echo "Wed 2026-11-25 11:00:00 CET" > "$W/fake/since/$B"
NOW=$(date -d '2026-11-25 12:00' +%s) ch --reap
check "batch started after 10:00 runs until 10:00 next day" running "$B"
NOW=$(date -d '2026-11-26 10:00' +%s) ch --reap
check "batch started after 10:00 stopped next day 10:00" bash -c "! grep -qxF -- '$B' '$W/fake/units'"
IDLEH=1; reset_units; add_running "$A"; echo "Wed 2026-11-25 08:00:00 CET" > "$W/fake/since/$A"; rm -rf "$LP"
OUT=$(PATH="$W/bin:$PATH" HOME="$H" FAKE="$W/fake" CLAUDE_HERE_ALLOWLIST="$W/allowlist" CLAUDE_HERE_STATE="$W/state" CGROUP_ROOT="$W/cg" PROC_ROOT="$W/proc" CLAUDE_HERE_NOW=$(date -d '2026-11-25 09:01' +%s) CLAUDE_HERE_IDLE_H=1 "$HERE/claude-here" --reap 2>&1)
check "no transcript: idle counts from start; CLAUDE_HERE_IDLE_H honoured" bash -c "! grep -qxF -- '$A' '$W/fake/units'"

echo "completion"
ch --complete folders; if grep -qxF "$H/landingpage" <<<"$OUT" && grep -qxF "$H/Documents/development/WG-Chores" <<<"$OUT" && ! grep -q evil <<<"$OUT" && ! grep -qxF "$H" <<<"$OUT"; then ok "completion lists allowlist folders"; else bad "completion folders" "$OUT"; fi
reset_units; add_running "$(unit "auto:$H/notes")"
ch --complete running; check "completion lists running session names" grep -qx 'fastpi-notes' <<<"$OUT"

echo "$PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]
