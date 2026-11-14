# Idempotent: every form with a password field (sign-up, change, forgot, first setup) checks the password through one expression policy that runs the password policy and adds a password-manager tip to every failure.
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/password-vault-hint.py
from authentik.policies.expression.models import ExpressionPolicy
from authentik.policies.password.models import PasswordPolicy
from authentik.stages.prompt.models import PromptStage

NAME = "password-check-vault-hint"
EXPRESSION = '''from authentik.policies.password.models import PasswordPolicy

result = PasswordPolicy.objects.get(name="enrollment-password-policy").passes(request)
if result.passing:
    return True
for message in result.messages:
    ak_message(message)
ak_message("Tip: use a password manager like KeePassXC or Bitwarden. It creates a long random password and remembers it for you.")
return False
'''

policy, created = ExpressionPolicy.objects.update_or_create(name=NAME, defaults={"expression": EXPRESSION})
print(f"POLICY {NAME}: {'created' if created else 'ok'}")

for stage in PromptStage.objects.all():
    if not stage.fields.filter(type="password").exists():
        continue
    before = [p.name for p in stage.validation_policies.all()]
    if before != [NAME]:
        stage.validation_policies.set([policy])
    print(f"STAGE {stage.name}: {'was ' + ','.join(before or ['none']) if before != [NAME] else 'ok'}")
