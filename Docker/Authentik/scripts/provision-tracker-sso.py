# Idempotent Authentik setup for the Tracker (Ryot on beefy): forward auth plus Ryot's OIDC login.
# The client id leaves as an "ENV Ryot/.env KEY=value" line, the secret as a "FILE Ryot/secrets/..." line, written on beefy by apply-sso-env.py:
#   cd Docker/Authentik && scp -q scripts/apply-sso-env.py beefy:/tmp/ \
#     && docker compose exec -T server ak shell < scripts/provision-tracker-sso.py 2>/dev/null \
#     | ssh beefy python3 /tmp/apply-sso-env.py --base /home/buntu/Projects/Docker
# Group streaming-users: everyone who may watch may track.
from authentik.core.models import Application, Group
from authentik.outposts.models import Outpost
from authentik.policies.models import PolicyBinding
from authentik.providers.oauth2.models import (
    ClientType, OAuth2Provider, RedirectURI, RedirectURIMatchingMode, RedirectURIType, ScopeMapping)
from authentik.providers.proxy.models import ProxyMode, ProxyProvider
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

# Ryot's own "Sign in with Holy Grail". Issuer https://sso.holy-grail.ch/application/o/tracker-login/,
# redirect <FRONTEND_URL>/api/auth. Hidden on the dashboard (dashboard-look.py HIDDEN).
ryot = oidc("tracker-login", ["https://tracker.holy-grail.ch/api/auth"])
app_for("tracker-login", "Tracker login", "https://tracker.holy-grail.ch", "streaming-users",
        provider=ryot)
print(f"ENV Ryot/.env SERVER_OIDC_CLIENT_ID={ryot.client_id}")


def secret_file(path, owner, mode, value):
    print(f"FILE {path} {owner} {mode} {value}")


secret_file("Ryot/secrets/ryot_oidc_client_secret", "1001:1001", "0400", ryot.client_secret)

outpost.save()
print("OK provisioned")
