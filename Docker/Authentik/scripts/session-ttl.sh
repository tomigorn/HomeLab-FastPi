#!/usr/bin/env bash
# Login lifetime: 1 day, or 30 days when the user ticks "stay signed in"; forward-auth apps 24 h.
#   session-ttl.sh apply | rollback | status
# apply saves the previous values first, then verifies a real login+MFA with the canary and rolls back on failure.
set -uo pipefail
cd /home/pi/Projects/Docker/Authentik
STATE=backups/session-ttl-before.json
OOB=/home/pi/Projects/Docker/_global/scripts/oob-alert.sh

shell() { sudo docker compose exec -T server ak shell 2>/dev/null | grep -vE 'objects imported|^###|^\s*$'; }

case "${1:-}" in
  status)
    shell <<'PY'
from authentik.stages.user_login.models import UserLoginStage
from authentik.providers.proxy.models import ProxyProvider
s = UserLoginStage.objects.get(name="default-authentication-login")
print("session_duration", s.session_duration, "remember_me_offset", s.remember_me_offset)
print("proxy validity", sorted({p.access_token_validity for p in ProxyProvider.objects.all()}))
PY
    ;;
  apply)
    mkdir -p backups && chmod 700 backups
    [ -e "$STATE" ] || shell <<'PY' > "$STATE"
import json
from authentik.stages.user_login.models import UserLoginStage
from authentik.providers.proxy.models import ProxyProvider
s = UserLoginStage.objects.get(name="default-authentication-login")
print(json.dumps({"session_duration": s.session_duration, "remember_me_offset": s.remember_me_offset,
                  "proxy": {p.name: p.access_token_validity for p in ProxyProvider.objects.all()}}))
PY
    chmod 600 "$STATE"
    python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$STATE" || { echo "STATE_SAVE_FAILED"; rm -f "$STATE"; exit 1; }
    shell <<'PY'
from authentik.stages.user_login.models import UserLoginStage
from authentik.providers.proxy.models import ProxyProvider
s = UserLoginStage.objects.get(name="default-authentication-login")
s.session_duration = "days=1"
s.remember_me_offset = "days=29"
s.save()
for p in ProxyProvider.objects.all():
    p.access_token_validity = "hours=24"
    p.save()
print("APPLIED")
PY
    if bash scripts/canary-verify.sh; then
      echo "SESSION_TTL_APPLIED_AND_VERIFIED"
      "$0" status
    else
      echo "VERIFY FAILED - rolling back"
      "$0" rollback
      bash "$OOB" $'🟠 <b>Authentik session-ttl apply failed</b>\n\n• Verification failed\n• Rolled back automatically' || true
      exit 1
    fi
    ;;
  rollback)
    [ -e "$STATE" ] || { echo "no saved state ($STATE)"; exit 1; }
    shell <<PY
import json
from authentik.stages.user_login.models import UserLoginStage
from authentik.providers.proxy.models import ProxyProvider
st = json.loads('''$(cat "$STATE")''')
s = UserLoginStage.objects.get(name="default-authentication-login")
s.session_duration = st["session_duration"]
s.remember_me_offset = st["remember_me_offset"]
s.save()
for p in ProxyProvider.objects.all():
    if p.name in st["proxy"]:
        p.access_token_validity = st["proxy"][p.name]
        p.save()
print("ROLLED_BACK")
PY
    rm -f "$STATE"
    ;;
  *) echo "usage: $0 apply|rollback|status"; exit 2 ;;
esac
