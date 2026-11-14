# Idempotent (review 2026-11-14): sign-up and the user settings refuse an email address another account already uses (any case).
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/unique-email.py
from authentik.policies.expression.models import ExpressionPolicy
from authentik.stages.prompt.models import PromptStage

NAME = "unique-email"
STAGES = ["invitation-enrollment-prompt-credentials-enrollment", "default-user-settings"]
EXPRESSION = '''from authentik.core.models import User

email = str((request.context.get("prompt_data") or {}).get("email") or "").strip()
if not email:
    return True
others = User.objects.filter(email__iexact=email)
if request.user.is_authenticated:
    others = others.exclude(pk=request.user.pk)
if others.exists():
    ak_message("This email address can't be used. Use a different one, or ask the admin.")
    return False
return True
'''

policy, created = ExpressionPolicy.objects.get_or_create(name=NAME, defaults={"expression": EXPRESSION})
if policy.expression != EXPRESSION:
    policy.expression = EXPRESSION
    policy.save()
    created = "updated"
print(f"POLICY {NAME}: {created if created == 'updated' else ('created' if created else 'ok')}")
for name in STAGES:
    stage = PromptStage.objects.get(name=name)
    missing = not stage.validation_policies.filter(pk=policy.pk).exists()
    if missing:
        stage.validation_policies.add(policy)
    print(f"STAGE {name}: {'added' if missing else 'ok'}")
