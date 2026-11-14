# Idempotent: every password policy requires the same rules as the invite sign-up (15+ characters, HIBP, zxcvbn >= 2, static rules).
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/password-policies.py
from authentik.policies.password.models import PasswordPolicy

RULES = {"length_min": 15, "check_have_i_been_pwned": True, "hibp_allowed_count": 0,
         "check_zxcvbn": True, "zxcvbn_score_threshold": 2, "check_static_rules": True}

for p in PasswordPolicy.objects.all():
    changed = [k for k, v in RULES.items() if getattr(p, k) != v]
    for k in changed:
        setattr(p, k, RULES[k])
    if changed:
        p.save()
    print(f"POLICY {p.name}: {'updated ' + ','.join(changed) if changed else 'ok'}")
