# Idempotent Authentik setup for homelab admin SSO (spec Docker/Authentik/docs/superpowers/specs/2026-10-18-homelab-admin-sso-design.md).
# Run: cd Docker/Authentik && docker compose exec -T server ak shell < scripts/provision-admin-sso.py \
#        | python3 scripts/apply-sso-env.py
# Secrets leave only as "ENV <path relative to Docker/> KEY=value" lines on stdout, which
# apply-sso-env.py writes into gitignored .env files.
#
# Every application created here is bound to the group homelab-admins: in Authentik an
# application with at least one binding is denied to everyone the bindings don't pass.
from authentik.core.models import Application, Group
from authentik.outposts.models import Outpost
from authentik.policies.models import PolicyBinding
from authentik.providers.oauth2.models import (
    ClientType, OAuth2Provider, RedirectURI, RedirectURIMatchingMode, RedirectURIType, ScopeMapping)
from authentik.providers.proxy.models import ProxyMode, ProxyProvider
import os
import secrets

admins = Group.objects.get(name="homelab-admins")
src = ProxyProvider.objects.get(name="cup-proxy")  # flows to copy (default authz/invalidation)
outpost = Outpost.objects.get(name="authentik Embedded Outpost")


def bind_admins(app):
    PolicyBinding.objects.get_or_create(target=app, group=admins, defaults={"order": 0})


def app_for(slug, name, provider, url):
    app, _ = Application.objects.update_or_create(
        slug=slug, defaults={"name": name, "provider": provider, "meta_launch_url": url})
    bind_admins(app)
    return app


def proxy(name, host, **extra):
    """Forward-auth (single application) proxy provider on the embedded outpost."""
    p, _ = ProxyProvider.objects.update_or_create(name=name, defaults={
        "mode": ProxyMode.FORWARD_SINGLE, "external_host": host,
        "authorization_flow": src.authorization_flow,
        "invalidation_flow": src.invalidation_flow, **extra})
    # What the API serializer does on create/update; the ORM alone leaves grant types,
    # redirect URIs and scope mappings (incl. scope-proxy, which carries user attributes
    # for basic-auth injection) empty until the next server restart reconciles them.
    p.set_oauth_defaults()
    p.save()
    outpost.providers.add(p)
    return p


OIDC_SCOPES = ["openid", "email", "profile", "offline_access"]
# By managed id, not scope_name: several custom mappings also use scope "email"/"profile".
oidc_mappings = [ScopeMapping.objects.get(managed=f"goauthentik.io/providers/oauth2/scope-{s}")
                 for s in OIDC_SCOPES]
oidc_src = OAuth2Provider.objects.get(name="Nextcloud")  # flows + signing key to copy


def oidc(name, redirects, logout_redirects=(), mappings=None, client_type=ClientType.CONFIDENTIAL):
    """OIDC provider, confidential unless client_type says otherwise. client_id/secret are
    generated once and kept on rerun (a PUBLIC client keeps an unused secret; Authentik
    never checks it). mappings replaces the default scope mappings (oidc_mappings) as a
    whole, on every run."""
    p, created = OAuth2Provider.objects.get_or_create(name=name, defaults={
        "client_id": secrets.token_urlsafe(30), "client_secret": secrets.token_urlsafe(60),
        "authorization_flow": oidc_src.authorization_flow,
        "invalidation_flow": oidc_src.invalidation_flow})
    p.authorization_flow = oidc_src.authorization_flow
    p.invalidation_flow = oidc_src.invalidation_flow
    p.signing_key = oidc_src.signing_key
    p.client_type = client_type
    p.grant_types = ["authorization_code", "refresh_token"]  # empty = every request rejected
    p.include_claims_in_id_token = True
    p.redirect_uris = (
        [RedirectURI(RedirectURIMatchingMode.STRICT, u, RedirectURIType.AUTHORIZATION) for u in redirects]
        + [RedirectURI(RedirectURIMatchingMode.STRICT, u, RedirectURIType.LOGOUT) for u in logout_redirects])
    p.save()
    p.property_mappings.set(oidc_mappings if mappings is None else mappings)
    return p


def env(path, **kv):
    for k, v in kv.items():
        print(f"ENV {path} {k}={v}")


# 1. Traefik dashboard (forward auth; Traefik route in Docker/Traefik/traefik/dynamic/dashboard.yml)
app_for("traefik-dashboard", "Traefik dashboard",
        proxy("traefik-dashboard-proxy", "https://traefik.holy-grail.ch"),
        "https://traefik.holy-grail.ch/dashboard/")

# 2. Grafana (Grafana's own generic_oauth; route in Docker/Traefik/traefik/dynamic/grafana.yml).
# Logout redirect is /login, not /logout: /logout itself bounces to Authentik's end-session,
# so registering it as post-logout target would make a loop possible.
grafana = oidc("grafana", ["https://grafana.holy-grail.ch/login/generic_oauth"],
               ["https://grafana.holy-grail.ch/login"])
app_for("grafana", "Grafana", grafana, "https://grafana.holy-grail.ch")
env("grafana/.env", GRAFANA_OAUTH_CLIENT_ID=grafana.client_id,
    GRAFANA_OAUTH_CLIENT_SECRET=grafana.client_secret)

# 3. Portainer (Portainer's own OAuth "Custom" provider, configured via its API; route in
# Docker/Traefik/traefik/dynamic/portainer.yml). Portainer uses its root URL as redirect.
portainer = oidc("portainer", ["https://portainer.holy-grail.ch/"])
app_for("portainer", "Portainer", portainer, "https://portainer.holy-grail.ch")
env("Portainer/.env", PORTAINER_OAUTH_CLIENT_ID=portainer.client_id,
    PORTAINER_OAUTH_CLIENT_SECRET=portainer.client_secret)

# 4. AdGuard Home (forward auth with HTTP Basic injection; route in
# Docker/Traefik/traefik/dynamic/adguard.yml). AdGuard has no header/SSO login, so the outpost
# sends Basic credentials of the dedicated AdGuard user `authentik-proxy` (its bcrypt hash is
# in Docker/adguard/conf/AdGuardHome.yaml). The outpost reads them from the merged user
# attributes (User.group_attributes(): group attrs, then user attrs on top), so they are stored
# on group homelab-admins. The password only comes in via env ADGUARD_PROXY_PASSWORD
# (`docker compose exec -T -e ADGUARD_PROXY_PASSWORD server ak shell ...`); without it the
# stored attributes are left untouched, so plain reruns don't wipe it.
app_for("adguard", "AdGuard Home",
        proxy("adguard-proxy", "https://adguard.holy-grail.ch", basic_auth_enabled=True,
              basic_auth_user_attribute="adguard_username",
              basic_auth_password_attribute="adguard_password"),
        "https://adguard.holy-grail.ch")
if os.environ.get("ADGUARD_PROXY_PASSWORD"):
    admins.attributes["adguard_username"] = "authentik-proxy"
    admins.attributes["adguard_password"] = os.environ["ADGUARD_PROXY_PASSWORD"]
    admins.save()

# 5. wg-easy (its own generic OIDC login; route in Docker/Traefik/traefik/dynamic/wg-easy.yml,
# config in Docker/WireguardVPN/docker-compose.yaml). wg-easy rejects a login whose userinfo
# says email_verified=false, which the default email mapping reports for every Authentik user.
# The addresses are trusted anyway (enrolment is invite-only with a verified email), so this
# provider gets its own email mapping instead of the default one. wg-easy links an Authentik
# login to an existing wg-easy user with the same email (auto-register stays off).
# Redirects: /api/auth/<provider>/callback (login) and /link (link from the profile page).
wg_email, _ = ScopeMapping.objects.update_or_create(name="wg-easy email (verified)", defaults={
    "scope_name": "email",
    "description": "Email address (marked verified: enrolment is invite-only + verified)",
    "expression": 'return {"email": request.user.email, "email_verified": True}'})
wg_easy = oidc("wg-easy", ["https://wg-easy.holy-grail.ch/api/auth/oidc/callback",
                           "https://wg-easy.holy-grail.ch/api/auth/oidc/link"],
               mappings=[m for m in oidc_mappings if not m.managed.endswith("scope-email")] + [wg_email])
app_for("wg-easy", "wg-easy (VPN admin)", wg_easy, "https://wg-easy.holy-grail.ch")
env("WireguardVPN/.env", WG_EASY_OIDC_CLIENT_ID=wg_easy.client_id,
    WG_EASY_OIDC_CLIENT_SECRET=wg_easy.client_secret)

# 6. Home Assistant (HA's own login via the hass-oidc-auth custom component; route in
# Docker/Traefik/traefik/dynamic/home-assistant.yml, config in
# Docker/Home-Assistant/config/configuration.yaml). PUBLIC client with PKCE, as the
# component recommends - no secret to leak. The client id is not secret; it goes into
# Home-Assistant/.env and reaches HA via compose env + !env_var. Roles come from the
# groups claim (part of the default profile mapping) and are set at first login only.
ha = oidc("home-assistant", ["https://ha.holy-grail.ch/auth/oidc/callback"],
          client_type=ClientType.PUBLIC)
app_for("home-assistant", "Home Assistant", ha, "https://ha.holy-grail.ch")
env("Home-Assistant/.env", HA_OIDC_CLIENT_ID=ha.client_id)

outpost.save()
print("OK provisioned")
