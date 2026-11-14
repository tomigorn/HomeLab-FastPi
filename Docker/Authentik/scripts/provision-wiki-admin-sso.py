# Idempotent Authentik setup for the admin guide (wiki-admin.holy-grail.ch): forward auth, bound to the group homelab-admins.
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/provision-wiki-admin-sso.py
# Remove again: same command with REMOVE = True.
from authentik.core.models import Application, Group
from authentik.outposts.models import Outpost
from authentik.policies.models import PolicyBinding
from authentik.providers.proxy.models import ProxyMode, ProxyProvider

REMOVE = False
HOST = "https://wiki-admin.holy-grail.ch"

if REMOVE:
    Application.objects.filter(slug="wiki-admin").delete()
    ProxyProvider.objects.filter(name="wiki-admin-proxy").delete()
    print("REMOVED")
else:
    outpost = Outpost.objects.get(name="authentik Embedded Outpost")
    admins = Group.objects.get(name="homelab-admins")
    src = ProxyProvider.objects.get(name="radarr-proxy")  # flows to copy
    p, _ = ProxyProvider.objects.update_or_create(name="wiki-admin-proxy", defaults={
        "mode": ProxyMode.FORWARD_SINGLE, "external_host": HOST, "access_token_validity": "hours=24",
        "authorization_flow": src.authorization_flow,
        "invalidation_flow": src.invalidation_flow})
    # Derives the redirect URIs from external_host; a bare ORM save leaves them empty.
    p.set_oauth_defaults()
    p.save()
    print("PROVIDER ok")
    app, _ = Application.objects.update_or_create(slug="wiki-admin", defaults={
        "name": "Admin guide", "provider": p, "meta_launch_url": HOST})
    print("APP ok")
    outpost.providers.add(p)
    print("OUTPOST ok")
    # An application with a binding is denied to everyone the bindings don't pass.
    PolicyBinding.objects.get_or_create(target=app, group=admins, defaults={"order": 0})
    print("BINDING ok")
