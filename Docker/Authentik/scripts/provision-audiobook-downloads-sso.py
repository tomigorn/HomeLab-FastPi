# Idempotent Authentik setup for fastpi's audiobook downloaders (mouse stack): qBittorrent, SABnzbd and Prowlarr behind forward auth, group streaming-admins.
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/provision-audiobook-downloads-sso.py
# Routes: Docker/Traefik/traefik/dynamic/qbittorrent-audiobooks.yml, sabnzbd-audiobooks.yml, prowlarr-audiobooks.yml. Groups: provision-media-groups.py (a unit test keeps both in step).
from authentik.core.models import Application, Group
from authentik.outposts.models import Outpost
from authentik.policies.models import PolicyBinding
from authentik.providers.proxy.models import ProxyMode, ProxyProvider

src = ProxyProvider.objects.get(name="radarr-proxy")  # flows to copy
outpost = Outpost.objects.get(name="authentik Embedded Outpost")


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


def app_for(slug, name, host, group):
    app, _ = Application.objects.update_or_create(
        slug=slug, defaults={"name": name, "provider": proxy(f"{slug}-proxy", host),
                             "meta_launch_url": host})
    PolicyBinding.objects.get_or_create(
        target=app, group=Group.objects.get(name=group), defaults={"order": 0})
    return app


app_for("qbittorrent-audiobooks", "qBittorrent", "https://qbittorrent-audiobooks.holy-grail.ch", "streaming-admins")
app_for("sabnzbd-audiobooks", "SABnzbd", "https://sabnzbd-audiobooks.holy-grail.ch", "streaming-admins")
app_for("prowlarr-audiobooks", "Prowlarr", "https://prowlarr-audiobooks.holy-grail.ch", "streaming-admins")

outpost.save()
print("OK provisioned")
