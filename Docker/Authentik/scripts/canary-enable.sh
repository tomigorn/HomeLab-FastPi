#!/usr/bin/env bash
# Enable the SSO test canary so a login test can run. Pair with canary-disable.sh.
set -euo pipefail
cd /home/pi/Projects/Docker/Authentik
sudo docker compose exec -T server ak shell <<'PY' 2>/dev/null
from authentik.core.models import User
u = User.objects.get(username="canary-test")
u.is_active = True
u.save()
print("CANARY_ENABLED is_active=%s" % u.is_active)
PY
