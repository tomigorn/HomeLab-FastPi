# Idempotent Authentik setup for the private notes (notes.holy-grail.ch): forward auth, access bound directly to one user (no group).
#   cd Docker/Authentik && docker compose exec -T -e NOTES_USER=<username> server ak shell < scripts/provision-notes-sso.py
# Canary test: add -e CANARY=add (temporary binding for canary-test) or -e CANARY=remove. Remove everything: -e REMOVE=1.
import os

from authentik.core.models import Application, User
from authentik.outposts.models import Outpost
from authentik.policies.models import PolicyBinding
from authentik.providers.proxy.models import ProxyMode, ProxyProvider

HOST = "https://notes.holy-grail.ch"
REMOVE = os.environ.get("REMOVE") == "1"
CANARY = os.environ.get("CANARY", "")

outpost = Outpost.objects.get(name="authentik Embedded Outpost")

if REMOVE:
    Application.objects.filter(slug="notes").delete()
    ProxyProvider.objects.filter(name="notes-proxy").delete()
    print("REMOVED")
elif CANARY:
    app = Application.objects.get(slug="notes")
    canary = User.objects.get(username="canary-test")
    if CANARY == "add":
        PolicyBinding.objects.get_or_create(target=app, user=canary, defaults={"order": 10})
    else:
        PolicyBinding.objects.filter(target=app, user=canary).delete()
    print("CANARY", CANARY)
else:
    owner = User.objects.get(username=os.environ["NOTES_USER"])
    src = ProxyProvider.objects.get(name="radarr-proxy")  # flows to copy
    p, _ = ProxyProvider.objects.update_or_create(name="notes-proxy", defaults={
        "mode": ProxyMode.FORWARD_SINGLE, "external_host": HOST, "access_token_validity": "hours=24",
        "authorization_flow": src.authorization_flow,
        "invalidation_flow": src.invalidation_flow})
    # Derives the redirect URIs from external_host; a bare ORM save leaves them empty.
    p.set_oauth_defaults()
    p.save()
    print("PROVIDER ok")
    app, _ = Application.objects.update_or_create(slug="notes", defaults={
        "name": "Notes", "provider": p, "meta_launch_url": HOST,
        "meta_description": "Private research notes"})
    print("APP ok")
    PolicyBinding.objects.get_or_create(target=app, user=owner, defaults={"order": 0})
    print("BINDING ok")
    outpost.providers.add(p)
    print("OUTPOST ok")

app = Application.objects.filter(slug="notes").first()
if app:
    print("BOUND", sorted(b.user.username for b in PolicyBinding.objects.filter(target=app) if b.user))
    print("OTHER_BINDINGS", PolicyBinding.objects.filter(target=app, user__isnull=True).count())
