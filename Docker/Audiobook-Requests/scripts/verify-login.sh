#!/usr/bin/env bash
# Functional check of the books login: canary on, into streaming-requesters, real login + ABR OIDC, then ALWAYS canary off (groups stripped).
set -uo pipefail
AK=/home/pi/Projects/Docker/Authentik
cleanup() { bash "$AK/scripts/canary-disable.sh" >/dev/null 2>&1 || true; echo "canary disabled (cleanup)"; }
trap cleanup EXIT
bash "$AK/scripts/canary-enable.sh" >/dev/null
(cd "$AK" && sudo docker compose exec -T server ak shell 2>/dev/null <<'PY' | grep CANARY
from authentik.core.models import Group, User
User.objects.get(username="canary-test").groups.add(Group.objects.get(name="streaming-requesters"))
print("CANARY_GROUP streaming-requesters")
PY
)
if python3 "$(dirname "$0")/verify_login.py"; then echo "BOOKS_LOGIN_OK"; exit 0; fi
echo "BOOKS_LOGIN_FAIL"; exit 1
