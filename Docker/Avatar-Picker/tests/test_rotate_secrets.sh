#!/usr/bin/env bash
# Rotation decision and metric file of scripts/rotate-secrets.sh. Usage: tests/test_rotate_secrets.sh
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }
# shellcheck disable=SC1091
source "$HERE/../scripts/rotate-secrets.sh"

NOW=1800000000; DAY=86400
needs_rotation never $NOW && ok "never-expiring token rotates" || bad "never-expiring token rotates"
needs_rotation $((NOW + 10 * DAY)) $NOW && ok "10 days left rotates" || bad "10 days left rotates"
needs_rotation $((NOW + 44 * DAY)) $NOW && ok "44 days left rotates" || bad "44 days left rotates"
needs_rotation $((NOW + 46 * DAY)) $NOW && bad "46 days left keeps" || ok "46 days left keeps"
needs_rotation $((NOW + 300 * DAY)) $NOW && bad "300 days left keeps" || ok "300 days left keeps"
needs_rotation garbage $NOW && ok "unreadable expiry rotates" || bad "unreadable expiry rotates"

TEXTFILE_DIR=$T write_metric $((NOW + 365 * DAY)) 1 $NOW
f=$T/authentik_tokens.prom
grep -qx "authentik_token_expires_timestamp_seconds{identifier=\"avatar-picker-api\"} $((NOW + 365 * DAY))" "$f" && ok "expiry metric" || bad "expiry metric" "$(cat "$f")"
grep -qx 'authentik_token_rotation_success{identifier="avatar-picker-api"} 1' "$f" && ok "success metric" || bad "success metric"
grep -qx "authentik_token_check_timestamp_seconds{identifier=\"avatar-picker-api\"} $NOW" "$f" && ok "check timestamp" || bad "check timestamp"
[[ $(stat -c %a "$f") == 644 ]] && ok "metric file 0644" || bad "metric file 0644"
TEXTFILE_DIR=$T write_metric never 0 $NOW
grep -qx 'authentik_token_expires_timestamp_seconds{identifier="avatar-picker-api"} 0' "$f" && ok "never = 0" || bad "never = 0"
ls "$T" | grep -qv '^authentik_tokens.prom$' && bad "no temp file left" || ok "no temp file left"

echo "PASS $PASS FAIL $FAIL"
[[ $FAIL -eq 0 ]]
