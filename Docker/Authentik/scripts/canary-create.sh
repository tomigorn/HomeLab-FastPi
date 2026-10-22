#!/usr/bin/env bash
# One-time: create the disabled SSO test canary (unprivileged, TOTP-enrolled).
# The account is is_active=False by default — it cannot log in until canary-enable.sh
# flips it, and canary-disable.sh flips it back. Credentials land in secrets/canary.env (600).
set -euo pipefail

PROJ="/home/pi/Projects/Docker/Authentik"
SECRETS="$PROJ/secrets"
SECRET_FILE="$SECRETS/canary.env"
USERNAME="canary-test"

mkdir -p "$SECRETS"; chmod 700 "$SECRETS"

PW="$(openssl rand -base64 24)"
read -r HEXKEY B32KEY < <(python3 -c "import os,base64; b=os.urandom(20); print(b.hex(), base64.b32encode(b).decode())")

cd "$PROJ"
sudo docker compose exec -T server ak shell <<PY
from authentik.core.models import User
from authentik.stages.authenticator_totp.models import TOTPDevice
u, created = User.objects.update_or_create(
    username="$USERNAME",
    defaults={"name": "SSO Canary (test only)", "is_active": False},
)
u.set_password("$PW")
u.save()
u.groups.clear()
TOTPDevice.objects.filter(user=u).delete()
TOTPDevice.objects.create(user=u, name="canary-totp", confirmed=True, digits=6, key="$HEXKEY")
print("CANARY_OK created=%s is_active=%s groups=%s" % (created, u.is_active, u.ak_groups.count()))
PY

umask 077
cat > "$SECRET_FILE" <<EOF
CANARY_USERNAME=$USERNAME
CANARY_PASSWORD=$PW
CANARY_TOTP_B32=$B32KEY
EOF
chmod 600 "$SECRET_FILE"
echo "canary created, DISABLED, unprivileged. Credentials: $SECRET_FILE (600)."
