# Idempotent Authentik setup for Dependency-Track (beefy): forward auth plus DT's own OIDC login, both group homelab-admins.
# The client id leaves as an "ENV Dependency-Track/.env KEY=value" line (public client, no secret), written on beefy by apply-sso-env.py:
#   cd Docker/Authentik && scp -q scripts/apply-sso-env.py beefy:/tmp/ \
#     && docker compose exec -T server ak shell < scripts/provision-dt-sso.py 2>/dev/null \
#     | ssh beefy python3 /tmp/apply-sso-env.py --base /home/buntu/Projects/Docker
from authentik.core.models import Application, Group
from authentik.outposts.models import Outpost
from authentik.policies.models import PolicyBinding
from authentik.providers.oauth2.models import (
    ClientType, OAuth2Provider, RedirectURI, RedirectURIMatchingMode, RedirectURIType, ScopeMapping)
from authentik.providers.proxy.models import ProxyMode, ProxyProvider
import secrets

HOST = "https://dt.holy-grail.ch"
admins = Group.objects.get(name="homelab-admins")
src = ProxyProvider.objects.get(name="cup-proxy")  # flows to copy
oidc_src = OAuth2Provider.objects.get(name="Nextcloud")  # flows + signing key to copy
outpost = Outpost.objects.get(name="authentik Embedded Outpost")


def app_for(slug, name, provider, url):
    app, _ = Application.objects.update_or_create(
        slug=slug, defaults={"name": name, "provider": provider, "meta_launch_url": url})
    PolicyBinding.objects.get_or_create(target=app, group=admins, defaults={"order": 0})
    return app


# Forward auth (route Docker/Traefik/traefik/dynamic/dt.yml), the dashboard tile.
p, _ = ProxyProvider.objects.update_or_create(name="dt-proxy", defaults={
    "mode": ProxyMode.FORWARD_SINGLE, "external_host": HOST,
    "authorization_flow": src.authorization_flow, "invalidation_flow": src.invalidation_flow})
# Derives the redirect URIs from external_host; a bare ORM save leaves them empty.
p.set_oauth_defaults()
p.save()
outpost.providers.add(p)
app_for("dt", "Dependency-Track", p, HOST)

# DT's own "Sign in with Holy Grail": the browser SPA is a PUBLIC client (code flow + PKCE), redirect /static/oidc-callback.html.
# The apiserver validates the ID token (aud = client id); groups (default profile mapping) -> DT team via the OIDC group mapping.
o, _ = OAuth2Provider.objects.get_or_create(name="dt-login", defaults={
    "client_id": secrets.token_urlsafe(30), "client_secret": secrets.token_urlsafe(60),
    "authorization_flow": oidc_src.authorization_flow, "invalidation_flow": oidc_src.invalidation_flow})
o.authorization_flow = oidc_src.authorization_flow
o.invalidation_flow = oidc_src.invalidation_flow
o.signing_key = oidc_src.signing_key
o.client_type = ClientType.PUBLIC
o.grant_types = ["authorization_code", "refresh_token"]  # empty = every request rejected
o.include_claims_in_id_token = True
o.redirect_uris = [RedirectURI(RedirectURIMatchingMode.STRICT, f"{HOST}/static/oidc-callback.html",
                               RedirectURIType.AUTHORIZATION)]
o.save()
o.property_mappings.set([ScopeMapping.objects.get(managed=f"goauthentik.io/providers/oauth2/scope-{s}")
                         for s in ("openid", "email", "profile")])
app_for("dt-login", "Dependency-Track login", o, HOST)  # hidden on the dashboard (dashboard-look.py HIDDEN)
print(f"ENV Dependency-Track/.env DT_OIDC_CLIENT_ID={o.client_id}")

outpost.save()
print("OK provisioned")
