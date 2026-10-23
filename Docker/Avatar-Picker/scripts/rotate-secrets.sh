#!/usr/bin/env bash
# Rotate the picker's credentials without printing them.
#   token-new     second API token for the avatar-picker service account -> secrets/authentik_token, recreate
#   token-finish  delete the old token, the new one takes over its identifier (run once the new one is verified)
#   header        new X-Picker-Secret -> secrets/picker_secret + Traefik dynamic/avatar-picker-secret.yml, recreate
set -euo pipefail
cd "$(dirname "$0")/.."
ID=avatar-picker-api
TRAEFIK_YML=../Traefik/traefik/dynamic/avatar-picker-secret.yml

ak() { sudo docker compose -f ../Authentik/docker-compose.yaml exec -T server ak shell 2>/dev/null; }
put() { printf %s "$2" | sudo install -o 65002 -g 65002 -m 0400 /dev/stdin "secrets/$1"; }
recreate() { docker compose up -d --force-recreate avatar-picker >/dev/null; }

case "${1:-}" in
  token-new)
    k=$(ak <<PY | sed -n 's/^TOKEN=//p'
from authentik.core.models import Token, TokenIntents
old = Token.objects.get(identifier="$ID")
Token.objects.filter(identifier="$ID-next").delete()
t = Token.objects.create(identifier="$ID-next", user=old.user, intent=TokenIntents.INTENT_API,
                         expiring=False, description=old.description)
print("TOKEN=" + t.key)
PY
)
    [ ${#k} -ge 40 ] || { echo "no token created"; exit 1; }
    put authentik_token "$k"; unset k
    recreate
    echo "TOKEN_SWITCHED"
    ;;
  token-finish)
    ak <<PY | grep -x FINISHED
from authentik.core.models import Token
assert Token.objects.filter(identifier="$ID-next").exists()
Token.objects.filter(identifier="$ID").delete()
Token.objects.filter(identifier="$ID-next").update(identifier="$ID")
print("FINISHED")
PY
    ;;
  header)
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
  *) echo "usage: $0 token-new|token-finish|header"; exit 2 ;;
esac
