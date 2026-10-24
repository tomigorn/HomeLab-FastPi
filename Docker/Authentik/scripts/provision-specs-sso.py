# Idempotent Authentik setup for Server-Specs (specs.holy-grail.ch): forward auth, open to every logged-in user (no group binding).
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/provision-specs-sso.py
# Remove again: same command with REMOVE = True.
from authentik.core.models import Application
from authentik.outposts.models import Outpost
from authentik.providers.proxy.models import ProxyMode, ProxyProvider

REMOVE = False
HOST = "https://specs.holy-grail.ch"

outpost = Outpost.objects.get(name="authentik Embedded Outpost")

if REMOVE:
    Application.objects.filter(slug="server-specs").delete()
    ProxyProvider.objects.filter(name="server-specs-proxy").delete()
    print("REMOVED")
else:
    src = ProxyProvider.objects.get(name="radarr-proxy")  # flows to copy
    p, _ = ProxyProvider.objects.update_or_create(name="server-specs-proxy", defaults={
        "mode": ProxyMode.FORWARD_SINGLE, "external_host": HOST,
        "authorization_flow": src.authorization_flow,
        "invalidation_flow": src.invalidation_flow})
    # Derives the redirect URIs from external_host; a bare ORM save leaves them empty.
    p.set_oauth_defaults()
    p.save()
    print("PROVIDER ok")
    Application.objects.update_or_create(slug="server-specs", defaults={
        "name": "Machines", "provider": p, "meta_launch_url": HOST})
    print("APP ok")
    outpost.providers.add(p)
    print("OUTPOST ok")
