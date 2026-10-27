#!/usr/bin/env bash
# Runs maintenance-silence.sh against a fake docker (amtool). Usage: scripts/test_maintenance_silence.sh
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }
has()  { grep -q -- "$2" "$3" && ok "$1" || bad "$1" "no [$2]"; }
hasnt() { grep -q -- "$2" "$3" && bad "$1" "unexpected [$2]" || ok "$1"; }

cat > "$T/docker" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
case "$*" in
  *"silence query -o json"*) cat "$FAKE_DIR/silences.json" ;;
  *"silence add"*) echo "new-id-1" ;;
  *"silence expire"*) exit 0 ;;
  *) echo "unexpected: $*" >&2; exit 9 ;;
esac
STUB
chmod +x "$T/docker"
cat > "$T/silences.json" <<'EOF2'
[{"id":"ours-1","createdBy":"maintenance-silence","comment":"maintenance: old","endsAt":"2026-10-27T12:00:00Z","status":{"state":"active"}},
 {"id":"foreign-1","createdBy":"someone","comment":"other","endsAt":"2026-10-27T12:00:00Z","status":{"state":"active"}},
 {"id":"ours-old","createdBy":"maintenance-silence","comment":"maintenance: done","endsAt":"2026-10-26T12:00:00Z","status":{"state":"expired"}}]
EOF2
export DOCKER="$T/docker" FAKE_LOG="$T/log" FAKE_DIR="$T"
S="$HERE/maintenance-silence.sh"

: > "$T/log"; out=$("$S" on 3 "Trixie upgrade" 2>&1); rc=$?
[[ $rc == 0 ]] && ok "on exits 0" || bad "on exits 0" "rc=$rc $out"
has "on replaces our active silence" "silence expire ours-1" "$T/log"
hasnt "on leaves foreign silences alone" "foreign-1" "$T/log"
hasnt "on ignores expired ones" "expire ours-old" "$T/log"
has "on adds for the given hours" "silence add --author=maintenance-silence --duration=3h" "$T/log"
has "on carries the reason" "maintenance: Trixie upgrade" "$T/log"
has "on silences the maintenance alerts" 'alertname=~"ContainerCrashLooping|ContainerDown|ContainerUnhealthy|SecurityFileChanged|HostRebooted|SshLoginOutsideLan"' "$T/log"
grep -q 'severity' "$T/log" && bad "never matches by severity" || ok "never matches by severity"
[[ $out == *new-id-1* ]] && ok "on prints the silence id" || bad "on prints the silence id" "$out"

: > "$T/log"; "$S" on >/dev/null 2>&1
has "default is 4 hours" "--duration=4h" "$T/log"

: > "$T/log"; "$S" on 30 >/dev/null 2>&1; rc=$?
[[ $rc != 0 ]] && ok "more than 24 h is refused" || bad "more than 24 h is refused"
hasnt "refused run adds nothing" "silence add" "$T/log"
"$S" on abc >/dev/null 2>&1 && bad "non-number refused" || ok "non-number refused"

: > "$T/log"; "$S" off >/dev/null 2>&1; rc=$?
[[ $rc == 0 ]] && ok "off exits 0" || bad "off exits 0"
has "off expires ours" "silence expire ours-1" "$T/log"
hasnt "off leaves foreign" "foreign-1" "$T/log"

out=$("$S" status 2>&1)
[[ $out == *ours-1* && $out != *foreign-1* ]] && ok "status lists only ours" || bad "status lists only ours" "$out"

"$S" bogus >/dev/null 2>&1 && bad "unknown command refused" || ok "unknown command refused"

echo "$PASS passed, $FAIL failed"
[[ $FAIL == 0 ]]
