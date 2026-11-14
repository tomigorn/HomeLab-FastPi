# Idempotent (review 2026-11-14): "Forgot password" refuses accounts without an authenticator and accepts no mailbox-based second factor; email links (sign-up, forgot password) expire after 10 min.
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/flow-hardening.py
from authentik.stages.authenticator_validate.models import AuthenticatorValidateStage
from authentik.stages.email.models import EmailStage

mfa = AuthenticatorValidateStage.objects.get(name="default-recovery-mfa")
want = {"not_configured_action": "deny", "device_classes": ["static", "totp", "webauthn"]}
changed = [k for k, v in want.items() if getattr(mfa, k) != v]
for k in changed:
    setattr(mfa, k, want[k])
if changed:
    mfa.save()
print(f"STAGE {mfa.name}: {'updated ' + ','.join(changed) if changed else 'ok'}")

for stage in EmailStage.objects.all():
    if stage.token_expiry != "minutes=10":
        stage.token_expiry = "minutes=10"
        stage.save()
        print(f"STAGE {stage.name}: updated token_expiry")
    else:
        print(f"STAGE {stage.name}: ok")
