# Idempotent Authentik setup for the Jellyfin beta channel (HomeLab-BeefyServer Docker/Jellyfin-Beta, route Docker/Traefik/traefik/dynamic/jellyfin-beta.yml): an OIDC provider + application cloned from prod's jellyfin-oidc / jellyfin (owner 2026-11-17).
# Run: bash scripts/provision-jellyfin-beta-sso.sh   (writes the client id/secret into beefy's Jellyfin-Beta/secrets/oidc.json, never printed)
# Rollback: ROLLBACK=1 in the exec environment (the .sh takes --rollback): deletes only this application and provider.
# Same flows, signing key, scopes, subject mode and group bindings as prod's application, so the beta's copied identity links map to the same users. Touches no flow, stage, existing provider or existing binding.
import json
import os

from authentik.core.models import Application
from authentik.policies.models import PolicyBinding
from authentik.providers.oauth2.models import OAuth2Provider, RedirectURI
import secrets

SLUG, NAME, PROVIDER = "jellyfin-beta", "Jellyfin Beta", "jellyfin-beta-oidc"
PROD_HOST, BETA_HOST = "https://jellyfin.holy-grail.ch", "https://jellyfin-beta.holy-grail.ch"

if os.environ.get("ROLLBACK") == "1":
    Application.objects.filter(slug=SLUG).delete()
    OAuth2Provider.objects.filter(name=PROVIDER).delete()
    print("OK rolled back")
    raise SystemExit(0)

src = OAuth2Provider.objects.get(name="jellyfin-oidc")
prod_app = Application.objects.get(provider=src)
p, _ = OAuth2Provider.objects.get_or_create(name=PROVIDER, defaults={
    "client_id": secrets.token_urlsafe(30), "client_secret": secrets.token_urlsafe(60),
    "authorization_flow": src.authorization_flow, "invalidation_flow": src.invalidation_flow})
for field in ("authorization_flow", "invalidation_flow", "authentication_flow", "signing_key", "encryption_key", "client_type", "grant_types",
              "include_claims_in_id_token", "sub_mode", "issuer_mode", "access_code_validity", "access_token_validity", "refresh_token_validity"):
    if hasattr(src, field):
        setattr(p, field, getattr(src, field))
redirects = [RedirectURI(r.matching_mode, r.url.replace(PROD_HOST, BETA_HOST), getattr(r, "redirect_uri_type", None)) if hasattr(r, "redirect_uri_type")
             else RedirectURI(r.matching_mode, r.url.replace(PROD_HOST, BETA_HOST)) for r in src.redirect_uris]
if not redirects or any(PROD_HOST in r.url or BETA_HOST not in r.url for r in redirects):
    raise SystemExit("prod redirect URIs do not all name the prod host: nothing changed for the redirects, check by hand")
p.redirect_uris = redirects
p.save()
p.property_mappings.set(src.property_mappings.all())

app, _ = Application.objects.update_or_create(slug=SLUG, defaults={
    "name": NAME, "provider": p, "meta_launch_url": BETA_HOST + "/",
    "meta_description": "Beta channel of Jellyfin: try things before prod", "group": prod_app.group, "policy_engine_mode": prod_app.policy_engine_mode})
other = PolicyBinding.objects.filter(target=prod_app, group__isnull=True).count()
for b in PolicyBinding.objects.filter(target=prod_app, group__isnull=False):
    PolicyBinding.objects.update_or_create(target=app, group=b.group, defaults={"order": b.order, "negate": b.negate, "enabled": b.enabled, "timeout": b.timeout})
groups = sorted(PolicyBinding.objects.filter(target=app, group__isnull=False).values_list("group__name", flat=True))
issuer = f"https://sso.holy-grail.ch/application/o/{SLUG}/"
print("OIDC_JSON " + json.dumps({"client_id": p.client_id, "client_secret": p.client_secret, "issuer": issuer, "public_url": BETA_HOST}))
print(f"OK provisioned {SLUG}: groups {', '.join(groups)}; prod bindings not copied (policy/user): {other}")
