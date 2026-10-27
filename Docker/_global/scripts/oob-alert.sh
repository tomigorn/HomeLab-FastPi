#!/usr/bin/env bash
# Out-of-band alert: Telegram directly, independent of the edge.
# DNS is resolved over DoH so this still works when AdGuard (the LAN DNS) is down,
# and the request never touches Traefik/the tunnel (outbound to api.telegram.org).
# The message is Telegram HTML: first line "<emoji> <b>Title</b>", then a blank line and "• " bullets; escape <, > and & in dynamic text.
# --check proves the path (token, chat, DNS-free route) without sending anything; --test sends a 🧪-marked message to TEST_CHAT_ID, or the alert chat when none is set.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${OOB_ENV:-$here/../secrets/oob-alert.env}"

api() {
  curl -sS --fail --max-time 20 --doh-url https://1.1.1.1/dns-query \
    "https://api.telegram.org/bot$(cat "$TOKEN_FILE")/$1" "${@:2}"
}

chat="$CHAT_ID"
case "${1:-}" in
  --check)
    api getChat --data-urlencode "chat_id=${CHAT_ID}" | grep -q '"ok":true' \
      && { echo "oob-alert: path ok (nothing sent)"; exit 0; } \
      || { echo "oob-alert: check FAILED" >&2; exit 1; }
    ;;
  --test)
    shift
    chat="${TEST_CHAT_ID:-$CHAT_ID}"
    msg="🧪 ${1:?usage: oob-alert.sh --test <html message>}"
    ;;
  *)
    msg="${1:?usage: oob-alert.sh [--check | --test] <html message>}"
    ;;
esac

api sendMessage \
  --data-urlencode "chat_id=${chat}" \
  --data-urlencode "text=${msg}" \
  --data "parse_mode=HTML" \
  --output /dev/null \
  && echo "oob-alert: sent" \
  || { echo "oob-alert: FAILED to send" >&2; exit 1; }
