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
from authentik.providers.proxy.models import ProxyMode, ProxyProvider

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
    outpost.providers.add(p)
    return p


# 1. Traefik dashboard (forward auth; Traefik route in Docker/Traefik/traefik/dynamic/dashboard.yml)
app_for("traefik-dashboard", "Traefik dashboard",
        proxy("traefik-dashboard-proxy", "https://traefik.holy-grail.ch"),
        "https://traefik.holy-grail.ch/dashboard/")

outpost.save()
print("OK provisioned")
