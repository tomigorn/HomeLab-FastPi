# Idempotent Authentik setup for Navidrome (music.holy-grail.ch): forward auth, group music-users; phone apps send Basic auth = username + app password, which the provider intercepts.
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/provision-music-sso.py
# Canary app password (1 day, key on stdout): -e CANARY_TOKEN=add, delete it again: -e CANARY_TOKEN=remove. Remove everything: -e REMOVE=1.
import os
from datetime import timedelta

from django.utils.timezone import now

from authentik.core.models import Application, Group, Token, TokenIntents, User
from authentik.outposts.models import Outpost
from authentik.policies.models import PolicyBinding
from authentik.providers.proxy.models import ProxyMode, ProxyProvider

HOST = "https://music.holy-grail.ch"
GROUP = "music-users"
CANARY_ID = "canary-test-music-poc"
REMOVE = os.environ.get("REMOVE") == "1"
CANARY_TOKEN = os.environ.get("CANARY_TOKEN", "")

outpost = Outpost.objects.get(name="authentik Embedded Outpost")

if REMOVE:
    Application.objects.filter(slug="music").delete()
    ProxyProvider.objects.filter(name="music-proxy").delete()
    Token.objects.filter(identifier=CANARY_ID).delete()
    print("REMOVED (group music-users kept)")
elif CANARY_TOKEN == "add":
    Token.objects.filter(identifier=CANARY_ID).delete()
    t = Token.objects.create(identifier=CANARY_ID, user=User.objects.get(username="canary-test"), intent=TokenIntents.INTENT_APP_PASSWORD, expiring=True, expires=now() + timedelta(days=1), description="Navidrome PoC test, delete after the test")
    print(t.key)
elif CANARY_TOKEN == "remove":
    print("CANARY_TOKEN deleted=%d" % Token.objects.filter(identifier=CANARY_ID).delete()[0])
else:
    group, _ = Group.objects.get_or_create(name=GROUP)
    print("GROUP ok")
    src = ProxyProvider.objects.get(name="radarr-proxy")  # flows to copy
    p, _ = ProxyProvider.objects.update_or_create(name="music-proxy", defaults={
        "mode": ProxyMode.FORWARD_SINGLE, "external_host": HOST, "access_token_validity": "hours=24",
        "intercept_header_auth": True,
        "authorization_flow": src.authorization_flow,
        "invalidation_flow": src.invalidation_flow})
    # Derives the redirect URIs from external_host; a bare ORM save leaves them empty.
    p.set_oauth_defaults()
    p.save()
    print("PROVIDER ok")
    app, _ = Application.objects.update_or_create(slug="music", defaults={
        "name": "Music", "provider": p, "meta_launch_url": HOST})
    print("APP ok")
    PolicyBinding.objects.get_or_create(target=app, group=group, defaults={"order": 10})
    print("BINDING ok")
    outpost.providers.add(p)
    print("OUTPOST ok")
