# Idempotent brute-force lockout for the login flow (authentik has none by default).
# Run (twice is fine):
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/provision-brute-force-policy.py
#
# A Reputation policy scores every source IP and username: each failed login
# subtracts 1, and the score decays over AUTHENTIK_REPUTATION__EXPIRY (default
# one day). Bound to default-authentication-flow, it denies the flow once a
# score drops below the threshold, so repeated guessing from an IP/user is
# throttled. Threshold -5 = five failed attempts before lockout: high enough
# that a normal mistyped password never locks the owner out.
#
# Touches ONLY this policy and its binding. MFA (the mfa-validation stage) and
# every other stage, policy and flow are left exactly as they are.
from authentik.flows.models import Flow
from authentik.policies.models import PolicyBinding
from authentik.policies.reputation.models import ReputationPolicy

POLICY_NAME = "homelab-brute-force-lockout"
THRESHOLD = -5
FLOW_SLUG = "default-authentication-flow"

policy, created = ReputationPolicy.objects.update_or_create(
    name=POLICY_NAME,
    defaults={"check_ip": True, "check_username": True, "threshold": THRESHOLD},
)
print(f"policy {'created' if created else 'updated'}: {policy.name} "
      f"ip={policy.check_ip} user={policy.check_username} threshold={policy.threshold}")

flow = Flow.objects.get(slug=FLOW_SLUG)
binding, bcreated = PolicyBinding.objects.update_or_create(
    policy=policy, target=flow,
    defaults={"enabled": True, "order": 0},
)
print(f"binding {'created' if bcreated else 'updated'}: {policy.name} -> {flow.slug} "
      f"enabled={binding.enabled} order={binding.order}")
