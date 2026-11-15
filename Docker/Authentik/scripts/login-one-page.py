# Idempotent (owner 2026-11-15): username and password on one page, then 2FA. Only the identification stage gets the password field; the password stage stays bound and skips itself (its policy default-authentication-flow-password-stage passes only while the user is not yet authenticated).
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/login-one-page.py
#   back to three pages: docker compose exec -T -e LOGIN_ONE_PAGE=rollback server ak shell < scripts/login-one-page.py
# Verify after either: bash scripts/canary-verify.sh (real login + 2FA with the canary).
import os

from authentik.stages.identification.models import IdentificationStage
from authentik.stages.password.models import PasswordStage

ident = IdentificationStage.objects.get(name="default-authentication-identification")
want = None if os.environ.get("LOGIN_ONE_PAGE") == "rollback" else PasswordStage.objects.get(name="default-authentication-password")

if ident.password_stage_id != (want.pk if want else None):
    ident.password_stage = want
    ident.save()
    print("STAGE identification: " + ("password field added" if want else "password field removed"))
else:
    print("STAGE identification: ok")
print("LOGIN: " + ("username + password on one page, then 2FA" if want else "three pages (username, password, 2FA)"))
