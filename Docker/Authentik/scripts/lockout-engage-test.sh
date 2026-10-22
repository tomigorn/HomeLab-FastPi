#!/usr/bin/env bash
# Prove the lockout actually engages: drive 5 failed-login reputation hits for a
# TEST IP (203.0.113.66, a reserved documentation range — never a real client),
# confirm that IP's auth flow is then DENIED while a different IP still PASSES,
# then delete the test reputation rows. No real account is touched.
set -euo pipefail
cd /home/pi/Projects/Docker/Authentik
sudo docker compose exec -T server ak shell <<'PY' 2>/dev/null
from django.test import RequestFactory
from django.contrib.auth.models import AnonymousUser
from authentik.flows.models import Flow
from authentik.policies.engine import PolicyEngine
from authentik.policies.reputation.signals import update_score
from authentik.policies.reputation.models import Reputation

TEST_IP = "203.0.113.66"
TEST_USER = "lockout-engage-test"
rf = RequestFactory()
flow = Flow.objects.get(slug="default-authentication-flow")

bad = rf.get("/"); bad.META["REMOTE_ADDR"] = TEST_IP
for _ in range(5):
    update_score(bad, TEST_USER, -1)

e = PolicyEngine(flow, AnonymousUser(), bad); e.use_cache = False; e.build()
print("BAD_IP_PASSING=%s (expect False = flow denied for the brute-forcer)" % e.passing)

good = rf.get("/"); good.META["REMOTE_ADDR"] = "203.0.113.9"
e2 = PolicyEngine(flow, AnonymousUser(), good); e2.use_cache = False; e2.build()
print("GOOD_IP_PASSING=%s (expect True = normal users unaffected)" % e2.passing)

n, _ = Reputation.objects.filter(identifier=TEST_USER, ip=TEST_IP).delete()
print("CLEANUP deleted=%s reputation row(s)" % n)
PY
