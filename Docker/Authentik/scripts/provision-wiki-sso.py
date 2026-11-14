# Idempotent Authentik setup for the Wiki (wiki.holy-grail.ch): forward auth, open to every logged-in user (no group binding).
# Public without login (skip_path_regex, one anchored regex per line): only the invite page /getting-started/ and the theme assets it loads. Everything else, search_index.json included, stays behind the SSO.
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/provision-wiki-sso.py
# Remove again: same command with REMOVE = True.
from authentik.core.models import Application
from authentik.outposts.models import Outpost
from authentik.providers.proxy.models import ProxyMode, ProxyProvider

REMOVE = False
HOST = "https://wiki.holy-grail.ch"
# A path segment never starts with a dot, so no .. or . segments can slip through.
SEG = r"[A-Za-z0-9_-][A-Za-z0-9._-]*"
PUBLIC_PATHS = "\n".join([
    r"^/getting-started/(index\.html)?$",
    rf"^/assets/(stylesheets|javascripts|css|images)(/{SEG})+$",
])

outpost = Outpost.objects.get(name="authentik Embedded Outpost")

if REMOVE:
    Application.objects.filter(slug="wiki").delete()
    ProxyProvider.objects.filter(name="wiki-proxy").delete()
    print("REMOVED")
else:
    src = ProxyProvider.objects.get(name="radarr-proxy")  # flows to copy
    p, _ = ProxyProvider.objects.update_or_create(name="wiki-proxy", defaults={
        "mode": ProxyMode.FORWARD_SINGLE, "external_host": HOST, "access_token_validity": "hours=24",
        "authorization_flow": src.authorization_flow,
        "invalidation_flow": src.invalidation_flow,
        "skip_path_regex": PUBLIC_PATHS})
    # Derives the redirect URIs from external_host; a bare ORM save leaves them empty.
    p.set_oauth_defaults()
    p.save()
    print("PROVIDER ok")
    Application.objects.update_or_create(slug="wiki", defaults={
        "name": "Guide", "provider": p, "meta_launch_url": HOST})
    print("APP ok")
    outpost.providers.add(p)
    print("OUTPOST ok")
