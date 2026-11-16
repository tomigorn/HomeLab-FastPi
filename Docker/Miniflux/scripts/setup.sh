#!/usr/bin/env bash
# Miniflux setup that has no API: secrets go to psql on stdin, never in argv or output.
usage() {
  cat <<'EOF'
Usage: Docker/Miniflux/scripts/setup.sh <step>
  api-key    API key for scripts/subscribe.py: secrets/api_key + a row in api_keys (description "subscribe.py"), idempotent
  feed-key   Vulnerability-Lookup watchlist feed key -> secrets/feed_key
  telegram   Telegram integration of MINIFLUX_ADMIN: the homelab bot (token file and chat id from Docker/_global/secrets/oob-alert.env)
Order on a fresh install: api-key, feed-key, scripts/subscribe.py, then telegram (enable it after the first fetch, or every old entry is sent).
EOF
}
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
secrets=${MINIFLUX_SECRETS:-$here/secrets}
admin=${MINIFLUX_ADMIN:-$(sed -n 's/^MINIFLUX_ADMIN=//p' "$here/.env")}

sql() { docker exec -i miniflux-db psql -q -v ON_ERROR_STOP=1 -U miniflux -d miniflux; }
quote() { local s=${1//\'/\'\'}; printf "'%s'" "$s"; }
user_id="(SELECT id FROM users WHERE username = $(quote "$admin"))"

case ${1:-} in
  api-key)
    [[ -s $secrets/api_key ]] || (umask 077; openssl rand -hex 32 | tr -d '\n' > "$secrets/api_key")
    echo "INSERT INTO api_keys (user_id, token, description) VALUES ($user_id, $(quote "$(< "$secrets/api_key")"), 'subscribe.py') ON CONFLICT (user_id, description) DO NOTHING;" | sql
    echo "api key ready (secrets/api_key)"
    ;;
  feed-key)
    (umask 077; docker exec vl-web vl-entrypoint provision --feed-key > "$secrets/feed_key.new")
    [[ -s $secrets/feed_key.new ]] && mv "$secrets/feed_key.new" "$secrets/feed_key"
    echo "feed key ready (secrets/feed_key)"
    ;;
  telegram)
    if [[ -z ${TELEGRAM_TOKEN_FILE:-} ]]; then
      # shellcheck source=/dev/null
      source "$here/../_global/secrets/oob-alert.env"
      TELEGRAM_TOKEN_FILE=$TOKEN_FILE TELEGRAM_CHAT_ID=$CHAT_ID
    fi
    echo "UPDATE integrations SET telegram_bot_enabled = true, telegram_bot_token = $(quote "$(< "$TELEGRAM_TOKEN_FILE")"), telegram_bot_chat_id = $(quote "$TELEGRAM_CHAT_ID"), telegram_bot_disable_web_page_preview = true WHERE user_id = $user_id;" | sql
    echo "telegram on for $admin"
    ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac
echo "next: python3 Docker/Miniflux/scripts/subscribe.py --dry-run"
