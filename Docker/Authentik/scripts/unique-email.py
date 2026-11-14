# Idempotent (review 2026-11-14): sign-up and the user settings refuse an email address another account already uses (any case); max 10 checks per hour per account or client IP.
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/unique-email.py
from authentik.policies.expression.models import ExpressionPolicy
from authentik.stages.prompt.models import PromptStage

NAME = "unique-email"
STAGES = ["invitation-enrollment-prompt-credentials-enrollment", "default-user-settings"]
EXPRESSION = '''from django.core.cache import cache

from authentik.core.models import User

email = str((request.context.get("prompt_data") or {}).get("email") or "").strip()
if not email:
    return True
if request.user.is_authenticated and email.lower() == (request.user.email or "").lower():
    return True
# At most 10 checks per hour per account (or per client IP during sign-up); after that every address is refused, so guessing reveals nothing.
key = f"unique-email:u{request.user.pk}" if request.user.is_authenticated else f"unique-email:ip{ak_client_ip}"
cache.add(key, 0, 3600)
tries = cache.incr(key)
others = User.objects.filter(email__iexact=email)
if request.user.is_authenticated:
    others = others.exclude(pk=request.user.pk)
if tries > 10 or others.exists():
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
