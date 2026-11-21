# Idempotent Authentik setup for the problem report site report.holy-grail.ch (beefy Seerr download-now report.py, route Docker/Traefik/traefik/dynamic/report.yml).
# Run: bash scripts/provision-report-sso.sh   Rollback: bash scripts/provision-report-sso.sh --rollback (deletes only this application and its provider).
# Forward auth (single application) on the embedded outpost, flows copied from radarr-proxy like tracker; groups streaming-users (reporters) and streaming-admins (see every report).
# Touches no flow, stage, existing provider or existing binding.
import os

from authentik.core.models import Application, Group
from authentik.outposts.models import Outpost
from authentik.policies.models import PolicyBinding
from authentik.providers.proxy.models import ProxyMode, ProxyProvider

SLUG, NAME, PROVIDER, HOST = "report", "Report a problem", "report-proxy", "https://report.holy-grail.ch"
GROUPS = ("streaming-users", "streaming-admins")
outpost = Outpost.objects.get(name="authentik Embedded Outpost")

if os.environ.get("ROLLBACK") == "1":
    Application.objects.filter(slug=SLUG).delete()
    for p in ProxyProvider.objects.filter(name=PROVIDER):
        outpost.providers.remove(p)
        p.delete()
    outpost.save()
    print("OK rolled back")
    raise SystemExit(0)

src = ProxyProvider.objects.get(name="radarr-proxy")
p, _ = ProxyProvider.objects.update_or_create(name=PROVIDER, defaults={
    "mode": ProxyMode.FORWARD_SINGLE, "external_host": HOST, "access_token_validity": "hours=24",
    "authorization_flow": src.authorization_flow, "invalidation_flow": src.invalidation_flow})
# derives the redirect URIs from external_host; a bare ORM save leaves them empty and the login dead-ends in "mismatching redirection URI"
p.set_oauth_defaults()
p.save()
outpost.providers.add(p)
tracker = Application.objects.filter(slug="tracker").first()
app, _ = Application.objects.update_or_create(slug=SLUG, defaults={
    "name": NAME, "provider": p, "meta_launch_url": HOST + "/", "meta_description": "Film or episode broken? Report it, it gets replaced",
    "group": tracker.group if tracker else ""})
for order, g in enumerate(GROUPS):
    PolicyBinding.objects.get_or_create(target=app, group=Group.objects.get(name=g), defaults={"order": order})
outpost.save()
groups = sorted(PolicyBinding.objects.filter(target=app, group__isnull=False).values_list("group__name", flat=True))
print(f"OK provisioned {SLUG}: mode {p.mode}, outpost {outpost.providers.filter(pk=p.pk).exists()}, groups {', '.join(groups)}, engine {app.policy_engine_mode}")
