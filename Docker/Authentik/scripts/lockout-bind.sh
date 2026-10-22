#!/usr/bin/env bash
# Reviewed, allowlisted write for the brute-force lockout (Option A).
# Binds the existing reputation policy `homelab-brute-force-lockout` to the
# authentication flow WITH Negate (deny only bad-reputation requests; the single
# checkbox that separates this from "lock everyone out"). Reversible: rollback
# deletes the binding (one row, no migration).
#   apply    -> create/update the binding (negate on, enabled, order 10)
#   rollback -> delete the binding
#   status   -> print the current binding(s)
set -euo pipefail
cd /home/pi/Projects/Docker/Authentik

case "${1:-}" in
  apply)
    sudo docker compose exec -T server ak shell <<'PY' 2>/dev/null
from authentik.flows.models import Flow
from authentik.policies.models import PolicyBinding
from authentik.policies.reputation.models import ReputationPolicy
flow = Flow.objects.get(slug="default-authentication-flow")
pol = ReputationPolicy.objects.get(name="homelab-brute-force-lockout")
pb, _ = PolicyBinding.objects.update_or_create(
    policy=pol, target=flow, defaults={"negate": True, "enabled": True, "order": 10})
pb.refresh_from_db()
assert pb.negate is True and pb.enabled is True, "NEGATE/ENABLED NOT SET"
print("BOUND pk=%s negate=%s enabled=%s order=%s" % (pb.pk, pb.negate, pb.enabled, pb.order))
PY
    ;;
  rollback)
    sudo docker compose exec -T server ak shell <<'PY' 2>/dev/null
from authentik.policies.models import PolicyBinding
n, _ = PolicyBinding.objects.filter(
    policy__reputationpolicy__name="homelab-brute-force-lockout",
    target__flow__slug="default-authentication-flow").delete()
print("ROLLED_BACK deleted=%s" % n)
PY
    ;;
  status)
    sudo docker compose exec -T server ak shell <<'PY' 2>/dev/null
from authentik.policies.models import PolicyBinding
qs = PolicyBinding.objects.filter(
    policy__reputationpolicy__name="homelab-brute-force-lockout",
    target__flow__slug="default-authentication-flow")
for pb in qs:
    print("BINDING pk=%s negate=%s enabled=%s order=%s" % (pb.pk, pb.negate, pb.enabled, pb.order))
print("count=%s" % qs.count())
PY
    ;;
  *)
    echo "usage: lockout-bind.sh apply|rollback|status" >&2; exit 2;;
esac
