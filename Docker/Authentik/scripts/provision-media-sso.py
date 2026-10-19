# Idempotent Authentik setup for the media apps on beefy that are gated by forward auth
# (the Radarr/Prowlarr/Bazarr/SABnzbd/qBittorrent apps were created by hand in the UI,
# see Docker/Traefik/docs/2026-10-06-authentik-sso.md; new ones are added here).
# Run: cd Docker/Authentik && docker compose exec -T server ak shell < scripts/provision-media-sso.py
#
# Unlike provision-admin-sso.py the group is per app: admin tools go to
# streaming-admins, apps meant for friends to streaming-users (the Jellyfin group).
from authentik.core.models import Application, Group
from authentik.outposts.models import Outpost
from authentik.policies.models import PolicyBinding
from authentik.providers.proxy.models import ProxyMode, ProxyProvider

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


def app_for(slug, name, host, group):
    app, _ = Application.objects.update_or_create(
        slug=slug, defaults={"name": name, "provider": proxy(f"{slug}-proxy", host),
                             "meta_launch_url": host})
    PolicyBinding.objects.get_or_create(
        target=app, group=Group.objects.get(name=group), defaults={"order": 0})
    return app


# Sonarr (route Docker/Traefik/traefik/dynamic/sonarr.yml), admins only like Radarr.
app_for("sonarr", "Sonarr", "https://sonarr.holy-grail.ch", "streaming-admins")

# Seerr (route Docker/Traefik/traefik/dynamic/requests.yml): everyone who may watch
# may request.
app_for("requests", "Requests", "https://requests.holy-grail.ch", "streaming-users")

outpost.save()
print("OK provisioned")
