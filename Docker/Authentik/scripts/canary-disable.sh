#!/usr/bin/env bash
# Disable the SSO test canary and strip any groups. Safe to run anytime; idempotent.
set -euo pipefail
cd /home/pi/Projects/Docker/Authentik
sudo docker compose exec -T server ak shell <<'PY' 2>/dev/null
from authentik.core.models import User
u = User.objects.get(username="canary-test")
u.is_active = False
u.groups.clear()
u.save()
print("CANARY_DISABLED is_active=%s groups=%s" % (u.is_active, u.groups.count()))
PY
