#!/usr/bin/env bash
# Runs the live CrowdSec parsers on sample Traefik lines: signed-in Seerr traffic is whitelisted, everything else is not.
set -uo pipefail
fail=0
CS_CONTAINER=${CS_CONTAINER:-crowdsec}
explain() { docker exec "$CS_CONTAINER" cscli explain --type traefik --log "$1" 2>&1; }
expect() {
  local want=$1 name=$2 line=$3 out got
  out=$(explain "$line")
  if grep -q 'local/requests-signed-in' <<<"$out" && grep -q 'whitelisted' <<<"$out"; then got=whitelisted; else got=counted; fi
  if [[ $got == "$want" ]]; then echo "PASS $name"; else echo "FAIL $name: $got, want $want"; fail=1; fi
}
ip=203.0.113.7
ts='31/Oct/2026:10:51:38 +0000'
expect whitelisted "seerr api reached the backend" \
  "$ip - - [$ts] \"GET /api/v1/request/42 HTTP/2.0\" 200 900 \"-\" \"-\" 1 \"requests@file\" \"http://192.168.1.102:5055\" 12ms"
expect whitelisted "download-now 403 from the backend" \
  "$ip - - [$ts] \"GET /_download-now/api?type=movie&tmdb=1 HTTP/2.0\" 403 52 \"-\" \"-\" 2 \"requests@file\" \"http://192.168.1.102:5055\" 90ms"
expect counted "seerr answered by a middleware (no session, ban, wake gate)" \
  "$ip - - [$ts] \"GET /api/v1/request/42 HTTP/2.0\" 403 9 \"-\" \"-\" 3 \"requests@file\" \"-\" 0ms"
expect counted "other router" \
  "$ip - - [$ts] \"GET /api/v1/request/42 HTTP/2.0\" 200 900 \"-\" \"-\" 4 \"jellyfin@file\" \"http://192.168.1.102:8096\" 12ms"
exit $fail
