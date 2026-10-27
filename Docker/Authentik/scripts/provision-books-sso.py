# Idempotent Authentik setup for AudioBookRequest (Docker/Audiobook-Requests): forward auth plus ABR's OIDC login, group streaming-requesters.
# The client id + secret leave only as a "FILE Audiobook-Requests/secrets/..." line, written by apply-sso-env.py; abr-setup.py hands them to ABR:
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/provision-books-sso.py 2>/dev/null | python3 scripts/apply-sso-env.py
# ABR maps the claim abr_groups: streaming-admins = ABR admin, streaming-requesters = trusted (auto-download, owner 2026-10-26), else untrusted.
# The limit of 5 books per 7 days (everyone) is enforced in front of ABR (Audiobook-Requests books-proxy + importer /quota).
from authentik.core.models import Application, Group
from authentik.outposts.models import Outpost
from authentik.policies.models import PolicyBinding
from authentik.providers.oauth2.models import (
    ClientType, OAuth2Provider, RedirectURI, RedirectURIMatchingMode, RedirectURIType, ScopeMapping)
from authentik.providers.proxy.models import ProxyMode, ProxyProvider
import json
import secrets

src = ProxyProvider.objects.get(name="radarr-proxy")  # flows to copy
outpost = Outpost.objects.get(name="authentik Embedded Outpost")
HOST = "https://books.holy-grail.ch"


def proxy(name, host):
    p, _ = ProxyProvider.objects.update_or_create(name=name, defaults={
        "mode": ProxyMode.FORWARD_SINGLE, "external_host": host, "access_token_validity": "hours=24",
        "authorization_flow": src.authorization_flow,
        "invalidation_flow": src.invalidation_flow})
    # Derives the redirect URIs from external_host; a bare ORM save leaves them empty.
    p.set_oauth_defaults()
    p.save()
    outpost.providers.add(p)
    return p


def oidc(name, redirects, extra_mappings=()):
    """Confidential OIDC provider like jellyfin-oidc (flows, signing key); client_id/secret are generated once and kept on rerun."""
    src_oidc = OAuth2Provider.objects.get(name="jellyfin-oidc")
    p, _ = OAuth2Provider.objects.get_or_create(name=name, defaults={
        "client_id": secrets.token_urlsafe(30), "client_secret": secrets.token_urlsafe(60),
        "authorization_flow": src_oidc.authorization_flow,
        "invalidation_flow": src_oidc.invalidation_flow})
    p.authorization_flow = src_oidc.authorization_flow
    p.invalidation_flow = src_oidc.invalidation_flow
    p.signing_key = src_oidc.signing_key
    p.client_type = ClientType.CONFIDENTIAL
    p.grant_types = ["authorization_code", "refresh_token"]  # empty = every request rejected
    p.include_claims_in_id_token = True
    p.redirect_uris = [RedirectURI(RedirectURIMatchingMode.STRICT, u, RedirectURIType.AUTHORIZATION)
                       for u in redirects]
    p.save()
    p.property_mappings.set([ScopeMapping.objects.get(managed=f"goauthentik.io/providers/oauth2/scope-{s}")
                             for s in ("openid", "email", "profile")] + list(extra_mappings))
    return p


def app_for(slug, name, host, group, provider=None):
    app, _ = Application.objects.update_or_create(
        slug=slug, defaults={"name": name, "provider": provider or proxy(f"{slug}-proxy", host),
                             "meta_launch_url": host})
    PolicyBinding.objects.get_or_create(
        target=app, group=Group.objects.get(name=group), defaults={"order": 0})
    return app


# Forward auth (route Docker/Traefik/traefik/dynamic/books.yml), the dashboard tile.
app_for("books", "Audiobook requests", HOST, "streaming-requesters")

groups, _ = ScopeMapping.objects.update_or_create(name="AudioBookRequest groups", defaults={
    "scope_name": "abr", "description": "ABR role (admin / trusted / untrusted)",
    "expression": (
        'groups = request.user.groups\n'
        'role = "admin" if groups.filter(name="streaming-admins").exists() else '
        '"trusted" if groups.filter(name="streaming-requesters").exists() else "untrusted"\n'
        'return {"abr_groups": [role]}')})

# ABR's "Login with OIDC" (Settings -> Security). Issuer https://sso.holy-grail.ch/application/o/books-login/. Hidden on the dashboard (dashboard-look.py HIDDEN).
login = oidc("books-login", [f"{HOST}/auth/oidc"], [groups])
app_for("books-login", "Audiobook requests login", HOST, "streaming-requesters", provider=login)
print("FILE Audiobook-Requests/secrets/abr_oidc_client.json 1000:1000 0400 "
      + json.dumps({"client_id": login.client_id, "client_secret": login.client_secret}, separators=(",", ":")))

outpost.save()
print("OK provisioned")
