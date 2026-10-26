# Idempotent Authentik setup for the Tracker (Floppy on beefy): forward auth plus Floppy's OIDC login.
# The allauth provider JSON (client id + secret) leaves as a "FILE Floppy/secrets/..." line, written on beefy by apply-sso-env.py:
#   cd Docker/Authentik && scp -q scripts/apply-sso-env.py beefy-direct:/tmp/ \
#     && docker compose exec -T server ak shell < scripts/provision-tracker-sso.py 2>/dev/null \
#     | ssh beefy-direct python3 /tmp/apply-sso-env.py --base /home/buntu/Projects/Docker
# Group streaming-users: everyone who may watch may track.
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


def proxy(name, host):
    """Forward-auth (single application) proxy provider on the embedded outpost."""
    p, _ = ProxyProvider.objects.update_or_create(name=name, defaults={
        "mode": ProxyMode.FORWARD_SINGLE, "external_host": host,
        "authorization_flow": src.authorization_flow,
        "invalidation_flow": src.invalidation_flow})
    # Derives the redirect URIs from external_host; a bare ORM save leaves them
    # empty and the login dead-ends in "mismatching redirection URI".
    p.set_oauth_defaults()
    p.save()
    outpost.providers.add(p)
    return p


def oidc(name, redirects):
    """Confidential OIDC provider like jellyfin-oidc (flows, signing key); scopes openid,
    email, profile. client_id/secret are generated once and kept on rerun."""
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
                             for s in ("openid", "email", "profile")])
    return p


def app_for(slug, name, host, group, provider=None):
    app, _ = Application.objects.update_or_create(
        slug=slug, defaults={"name": name, "provider": provider or proxy(f"{slug}-proxy", host),
                             "meta_launch_url": host})
    PolicyBinding.objects.get_or_create(
        target=app, group=Group.objects.get(name=group), defaults={"order": 0})
    return app


# Forward auth (route Docker/Traefik/traefik/dynamic/tracker.yml), the dashboard tile.
app_for("tracker", "Tracker", "https://tracker.holy-grail.ch", "streaming-users")

# Floppy's own "Sign in with Holy Grail" (allauth openid_connect, provider id authentik). Issuer
# https://sso.holy-grail.ch/application/o/tracker-login/. Hidden on the dashboard (dashboard-look.py HIDDEN).
REDIRECTS = ["https://tracker.holy-grail.ch/accounts/oidc/authentik/login/callback/"]
login = oidc("tracker-login", REDIRECTS)
app_for("tracker-login", "Tracker login", "https://tracker.holy-grail.ch", "streaming-users",
        provider=login)

providers = {"openid_connect": {"OAUTH_PKCE_ENABLED": True, "APPS": [{
    "provider_id": "authentik", "name": "Holy Grail",
    "client_id": login.client_id, "secret": login.client_secret,
    "settings": {"server_url": "https://sso.holy-grail.ch/application/o/tracker-login/.well-known/openid-configuration"}}]}}
print(f"FILE Floppy/secrets/floppy_oidc_providers 65125:65125 0400 {json.dumps(providers, separators=(',', ':'))}")

outpost.save()
print("OK provisioned")
