#!/usr/bin/env bash
# Rotate the picker's credentials without printing them.
#   token-auto    weekly timer: rotate when the API token expires within ROTATE_BEFORE_DAYS (or never expires), write the metric
#   token-rotate  token-new, verify as the container, token-finish; on a failed verify the old token goes back
#   token-new     second API token (expires in TOKEN_DAYS) for the avatar-picker service account -> secrets/authentik_token, recreate
#   token-verify  the running container lists one user with its token
#   token-finish  delete the old token, the new one takes over its identifier
#   token-metric  write the expiry metric only
#   header        new X-Picker-Secret -> secrets/picker_secret + Traefik dynamic/avatar-picker-secret.yml, recreate
set -euo pipefail
ID=avatar-picker-api
TOKEN_DAYS=${TOKEN_DAYS:-365}
ROTATE_BEFORE_DAYS=${ROTATE_BEFORE_DAYS:-45}
TEXTFILE_DIR=${TEXTFILE_DIR:-/var/lib/node-exporter/textfile}
TRAEFIK_YML=../Traefik/traefik/dynamic/avatar-picker-secret.yml

needs_rotation() { # needs_rotation <expires epoch|never> <now>
  [[ $1 =~ ^[0-9]+$ ]] || return 0
  (( $1 - $2 < ROTATE_BEFORE_DAYS * 86400 ))
}

write_metric() { # write_metric <expires epoch|never> <rotation ok 0|1> [now]
  local exp=$1 now=${3:-$(date +%s)} tmp
  [[ $exp =~ ^[0-9]+$ ]] || exp=0
  tmp=$(mktemp "$TEXTFILE_DIR/.authentik_tokens.XXXX")
  cat > "$tmp" <<EOF
# HELP authentik_token_expires_timestamp_seconds Expiry of an Authentik service API token (0 = never expires).
# TYPE authentik_token_expires_timestamp_seconds gauge
authentik_token_expires_timestamp_seconds{identifier="$ID"} $exp
# HELP authentik_token_rotation_success Last rotation check of the token succeeded (1) or failed (0).
# TYPE authentik_token_rotation_success gauge
authentik_token_rotation_success{identifier="$ID"} $2
# HELP authentik_token_check_timestamp_seconds Time of the last rotation check.
# TYPE authentik_token_check_timestamp_seconds gauge
authentik_token_check_timestamp_seconds{identifier="$ID"} $now
EOF
  chmod 0644 "$tmp"
  mv "$tmp" "$TEXTFILE_DIR/authentik_tokens.prom"
}

ak() { sudo docker compose -f ../Authentik/docker-compose.yaml exec -T server ak shell 2>/dev/null; }
put() { printf %s "$2" | sudo install -o 65002 -g 65002 -m 0400 /dev/stdin "secrets/$1"; }
recreate() { docker compose up -d --force-recreate avatar-picker >/dev/null; }

expires() { # epoch, or "never"
  ak <<PY | sed -n 's/^EXPIRES=//p'
from authentik.core.models import Token
t = Token.objects.get(identifier="$ID")
print("EXPIRES=" + (str(int(t.expires.timestamp())) if t.expiring and t.expires else "never"))
PY
}

token_new() {
  local k
  k=$(ak <<PY | sed -n 's/^TOKEN=//p'
from datetime import timedelta
from django.utils.timezone import now
from authentik.core.models import Token, TokenIntents
old = Token.objects.get(identifier="$ID")
Token.objects.filter(identifier="$ID-next").delete()
t = Token.objects.create(identifier="$ID-next", user=old.user, intent=TokenIntents.INTENT_API,
                         expiring=True, expires=now() + timedelta(days=$TOKEN_DAYS), description=old.description)
print("TOKEN=" + t.key)
PY
)
  [ ${#k} -ge 40 ] || { echo "no token created"; return 1; }
  put authentik_token "$k"; unset k
  recreate
  echo "TOKEN_SWITCHED"
}

token_verify() {
  local i
  for i in $(seq 1 20); do
    docker exec -i avatar-picker python - 2>/dev/null <<'PY' | grep -qx TOKEN_OK && { echo TOKEN_OK; return 0; }
import os, sys
sys.path.insert(0, "/app")
from authentik_api import Client
c = Client(os.environ["AUTHENTIK_URL"], open(os.environ["AUTHENTIK_TOKEN_FILE"]).read().strip())
d = c._call("GET", "/api/v3/core/users/?page_size=1")
print("TOKEN_OK" if "results" in d else "TOKEN_BAD")
PY
    sleep 3
  done
  echo "TOKEN_VERIFY_FAILED"; return 1
}

token_rollback() {
  local k
  k=$(ak <<PY | sed -n 's/^TOKEN=//p'
from authentik.core.models import Token
Token.objects.filter(identifier="$ID-next").delete()
print("TOKEN=" + Token.objects.get(identifier="$ID").key)
PY
)
  [ ${#k} -ge 40 ] || { echo "ROLLBACK_FAILED"; return 1; }
  put authentik_token "$k"; unset k
  recreate
  echo "ROLLED_BACK"
}

token_finish() {
  ak <<PY | grep -x FINISHED
from authentik.core.models import Token
assert Token.objects.filter(identifier="$ID-next").exists()
Token.objects.filter(identifier="$ID").delete()
Token.objects.filter(identifier="$ID-next").update(identifier="$ID")
print("FINISHED")
PY
}

token_rotate() {
  token_new || return 1
  if ! token_verify; then token_rollback; return 1; fi
  token_finish
}

main() {
  cd "$(dirname "$0")/.."
  case "${1:-}" in
    token-auto)
      local exp ok=1
      exp=$(expires) || exp=""
      if needs_rotation "${exp:-x}" "$(date +%s)"; then
        if token_rotate; then exp=$(expires) || ok=0; else ok=0; fi
      fi
      write_metric "${exp:-never}" "$ok"
      [ "$ok" = 1 ]
      ;;
    token-rotate) token_rotate; write_metric "$(expires)" 1 ;;
    token-new) token_new ;;
    token-verify) token_verify ;;
    token-finish) token_finish ;;
    token-metric) write_metric "$(expires)" 1 ;;
    header)
      local s tmp
      s=$(openssl rand -hex 32)
      put picker_secret "$s"
      tmp=$(mktemp "$TRAEFIK_YML.XXXX")
      sed -E "s|^( *X-Picker-Secret: ).*|\1\"$s\"|" ../Traefik/traefik/dynamic-example/avatar-picker-secret.yml > "$tmp"; unset s
      chgrp 65026 "$tmp" 2>/dev/null || sudo chgrp 65026 "$tmp"
      chmod 0640 "$tmp"
      mv "$tmp" "$TRAEFIK_YML"
      recreate
      echo "HEADER_SWITCHED"
      ;;
    *) echo "usage: $0 token-auto|token-rotate|token-new|token-verify|token-finish|token-metric|header"; exit 2 ;;
  esac
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; fi
