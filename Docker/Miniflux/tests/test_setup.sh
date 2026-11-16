#!/usr/bin/env bash
# Tests for scripts/setup.sh: secrets only travel on stdin, SQL quoting, idempotent statements.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fails=0
ok() { echo "PASS $1"; }
bad() { echo "FAIL $1: $2"; fails=$((fails + 1)); }

# fake docker: records argv and stdin
mkdir "$T/bin"
cat > "$T/bin/docker" <<EOF
#!/usr/bin/env bash
echo "ARGV \$*" >> "$T/log"
if [[ \$* == *"provision_watchlists.py --feed-key"* || \$* == *"provision --feed-key"* ]]; then printf 'FEEDKEY123'; exit 0; fi
cat >> "$T/log"; echo >> "$T/log"
EOF
chmod +x "$T/bin/docker"
printf "12345:AA'bb" > "$T/token"
mkdir "$T/secrets"
export PATH="$T/bin:$PATH" MINIFLUX_SECRETS="$T/secrets" TELEGRAM_TOKEN_FILE="$T/token" TELEGRAM_CHAT_ID="-100777" MINIFLUX_ADMIN=jane-admin

bash "$HERE/../scripts/setup.sh" api-key >/dev/null 2>&1
key=$(cat "$T/secrets/api_key" 2>/dev/null)
[[ ${#key} -ge 40 ]] && ok api-key-written || bad api-key-written "len ${#key}"
grep -q "ON CONFLICT (user_id, description) DO NOTHING" "$T/log" && ok api-key-idempotent || bad api-key-idempotent "$(cat "$T/log")"
grep "^ARGV" "$T/log" | grep -q "$key" && bad api-key-not-in-argv "key in argv" || ok api-key-not-in-argv

bash "$HERE/../scripts/setup.sh" feed-key >/dev/null 2>&1
[[ $(cat "$T/secrets/feed_key" 2>/dev/null) == FEEDKEY123 ]] && ok feed-key-written || bad feed-key-written "$(cat "$T/secrets/feed_key" 2>&1)"

: > "$T/log"
out=$(bash "$HERE/../scripts/setup.sh" telegram 2>&1)
grep -q "telegram_bot_token = '12345:AA''bb'" "$T/log" && ok telegram-quoted || bad telegram-quoted "$(cat "$T/log")"
grep -q "telegram_bot_chat_id = '-100777'" "$T/log" && ok telegram-chat || bad telegram-chat "$(cat "$T/log")"
grep "^ARGV" "$T/log" | grep -q "AA" && bad telegram-not-in-argv "token in argv" || ok telegram-not-in-argv
[[ $out == *12345* ]] && bad telegram-not-printed "$out" || ok telegram-not-printed

bash "$HERE/../scripts/setup.sh" --help | grep -q "api-key" && ok help || bad help "no usage"

echo "$fails failed"
(( fails == 0 ))
