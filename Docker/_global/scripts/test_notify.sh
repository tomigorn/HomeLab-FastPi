#!/usr/bin/env bash
# Runs notify.sh against a fake oob-alert.sh and a temp textfile. Usage: scripts/test_notify.sh
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }
has()  { grep -qF -- "$2" "$3" && ok "$1" || bad "$1" "no [$2]"; }
hasnt() { grep -qF -- "$2" "$3" && bad "$1" "unexpected [$2]" || ok "$1"; }

printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$@" >> "%s/oob.log"\n' "$T" > "$T/oob"
chmod +x "$T/oob"
export NOTIFY_OOB="$T/oob" NOTIFY_PROM="$T/digest_notes.prom"
S="$HERE/notify.sh"
M=homelab_digest_note_timestamp_seconds

: > "$T/oob.log"; "$S" action "🔴 <b>Restore test FAILED</b>" >/dev/null
has "action goes to oob-alert.sh unchanged" "🔴 <b>Restore test FAILED</b>" "$T/oob.log"
[[ -e $NOTIFY_PROM ]] && bad "action writes no digest note" || ok "action writes no digest note"

: > "$T/oob.log"; NOTIFY_NOW=1000000 "$S" digest restore-test "Restore test passed: 12 files" >/dev/null
[[ -s $T/oob.log ]] && bad "digest sends nothing" || ok "digest sends nothing"
has "digest note as a metric with its time" "$M{source=\"restore-test\",text=\"Restore test passed: 12 files\"} 1000000" "$NOTIFY_PROM"
has "HELP line" "# HELP $M " "$NOTIFY_PROM"
has "TYPE gauge" "# TYPE $M gauge" "$NOTIFY_PROM"
[[ $(stat -c %a "$NOTIFY_PROM") == 644 ]] && ok "file mode 0644" || bad "file mode 0644" "$(stat -c %a "$NOTIFY_PROM")"

NOTIFY_NOW=1000060 "$S" digest restore-test "Restore test passed: 12 files" >/dev/null
[[ $(grep -c "^$M{" "$NOTIFY_PROM") == 1 ]] && ok "same note again: one line" || bad "same note again: one line" "$(cat "$NOTIFY_PROM")"
has "same note again: newest time" "12 files\"} 1000060" "$NOTIFY_PROM"

NOTIFY_NOW=1000100 "$S" digest netns-watch $'say "hi" \\ back\nline two' >/dev/null
has "quote, backslash and newline escaped" "text=\"say \\\"hi\\\" \\\\ back line two\"} 1000100" "$NOTIFY_PROM"
[[ $(grep -c "^$M{" "$NOTIFY_PROM") == 2 ]] && ok "two different notes kept" || bad "two different notes kept"

long=$(printf 'x%.0s' {1..400})
NOTIFY_NOW=1000200 "$S" digest long "$long" >/dev/null
[[ $(grep -o 'source="long",text="x*' "$NOTIFY_PROM" | grep -o 'x*$' | wc -c) -le 301 ]] && ok "text capped at 300 characters" || bad "text capped at 300 characters"

NOTIFY_NOW=$((1000200 + 172801)) "$S" digest later "new one" >/dev/null
[[ $(grep -c "^$M{" "$NOTIFY_PROM") == 1 ]] && ok "notes older than 48 h pruned" || bad "notes older than 48 h pruned" "$(grep -c "^$M{" "$NOTIFY_PROM")"
has "newest note kept" 'source="later"' "$NOTIFY_PROM"

"$S" digest "Bad Source!" "x" >/dev/null 2>&1; rc=$?
[[ $rc == 2 ]] && ok "bad source refused (exit 2)" || bad "bad source refused (exit 2)" "rc=$rc"
"$S" digest src "" >/dev/null 2>&1 && bad "empty text refused" || ok "empty text refused"
"$S" bogus x >/dev/null 2>&1; [[ $? == 2 ]] && ok "unknown mode exit 2" || bad "unknown mode exit 2"
"$S" --help | grep -q "notify.sh action" && ok "--help shows usage" || bad "--help shows usage"

ls "$T" | grep -v '\.lock$' | grep -q 'digest_notes\.prom\.' && bad "no temp files left" "$(ls "$T")" || ok "no temp files left"

echo "notify: $PASS passed, $FAIL failed"
[[ $FAIL == 0 ]]
