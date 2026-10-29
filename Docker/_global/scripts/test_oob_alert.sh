#!/usr/bin/env bash
# Runs oob-alert.sh against a fake curl. Usage: scripts/test_oob_alert.sh
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }
has()  { grep -q -- "$2" "$3" && ok "$1" || bad "$1" "no [$2]"; }
hasnt() { grep -q -- "$2" "$3" && bad "$1" "unexpected [$2]" || ok "$1"; }

cat > "$T/curl" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$@" >> "$FAKE_LOG"
cfg=; for a; do [[ $a == -K || $a == --config ]] && cfg=$(cat); done
printf '%s\n' "$cfg" >> "$FAKE_CFG"
case "$* $cfg" in
  *getChat*) echo '{"ok":true,"result":{"id":-100,"type":"supergroup"}}' ;;
  *getMe*) echo '{"ok":true,"result":{"is_bot":true}}' ;;
esac
exit 0
STUB
chmod +x "$T/curl"
echo token123 > "$T/token"
printf 'TOKEN_FILE=%s\nCHAT_ID=-100\n' "$T/token" > "$T/env"
export OOB_ENV="$T/env" FAKE_LOG="$T/log" FAKE_CFG="$T/cfg" PATH="$T:$PATH"
S="$HERE/oob-alert.sh"

: > "$T/log"; : > "$T/cfg"; "$S" "🔴 <b>Page</b>" >/dev/null 2>&1
has "page goes to sendMessage" "sendMessage" "$T/cfg"
has "page to the alert chat" "chat_id=-100" "$T/log"
has "page text unchanged" "text=🔴 <b>Page</b>" "$T/log"

: > "$T/log"; : > "$T/cfg"; out=$("$S" --check 2>&1); rc=$?
[[ $rc == 0 && $out == *ok* ]] && ok "check exits 0" || bad "check exits 0" "rc=$rc $out"
hasnt "check sends no message" "sendMessage" "$T/cfg"
has "check reads the chat" "getChat" "$T/cfg"

: > "$T/log"; : > "$T/cfg"; "$S" --test "<b>Batch start</b>" >/dev/null 2>&1
has "test is marked" "text=🧪 <b>Batch start</b>" "$T/log"
has "test without TEST_CHAT_ID goes to the alert chat" "chat_id=-100" "$T/log"

printf 'TEST_CHAT_ID=-200\n' >> "$T/env"
: > "$T/log"; : > "$T/cfg"; "$S" --test "x" >/dev/null 2>&1
has "test goes to TEST_CHAT_ID when set" "chat_id=-200" "$T/log"
: > "$T/log"; : > "$T/cfg"; "$S" "real page" >/dev/null 2>&1
has "a page still goes to the alert chat" "chat_id=-100" "$T/log"

"$S" >/dev/null 2>&1 && bad "no message refused" || ok "no message refused"

: > "$T/log"; : > "$T/cfg"; "$S" "secret check" >/dev/null 2>&1; "$S" --check >/dev/null 2>&1
hasnt "token never in curl argv" "token123" "$T/log"
has "token URL via curl config on stdin" 'url = "https://api.telegram.org/bottoken123/sendMessage"' "$T/cfg"
has "check URL via curl config on stdin" 'url = "https://api.telegram.org/bottoken123/getChat"' "$T/cfg"

echo "$PASS passed, $FAIL failed"
[[ $FAIL == 0 ]]
