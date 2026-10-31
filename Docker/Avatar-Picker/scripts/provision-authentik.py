# Idempotent Authentik setup for the avatar picker.
# Run: docker compose -f Docker/Authentik/docker-compose.yaml exec -T server ak shell < this file
# Prints the API token as "TOKEN=..." on stdout - redirect it into secrets/authentik_token,
# never into git.
from datetime import timedelta

from django.utils.timezone import now

from authentik.core.models import Application, Token, TokenIntents, User, UserTypes
from authentik.outposts.models import Outpost
from authentik.providers.proxy.models import ProxyMode, ProxyProvider
from authentik.rbac.models import Role
from authentik.tenants.models import Tenant

# 1. service account + least-privilege role (view/change users only)
sa, _ = User.objects.get_or_create(
    username="avatar-picker",
    defaults={"name": "Avatar picker (service)", "type": UserTypes.INTERNAL_SERVICE_ACCOUNT},
)
role, _ = Role.objects.get_or_create(name="avatar-picker")
for codename in ("view_user", "change_user"):
    role.assign_perms(f"authentik_core.{codename}")
role.users.add(sa)  # 2026.8: roles bind directly to users

# 2. API token, 365 days; scripts/rotate-secrets.sh token-auto renews it
tok, _ = Token.objects.get_or_create(
    identifier="avatar-picker-api",
    defaults={"user": sa, "intent": TokenIntents.INTENT_API, "expiring": True,
              "expires": now() + timedelta(days=365),
              "description": "Avatar picker - writes attributes.avatar"},
)

# 3. forward-auth proxy provider + application for avatars.holy-grail.ch
#    (no policy binding = every active Authentik user may open it)
src = ProxyProvider.objects.get(name="cup-proxy")
prov, _ = ProxyProvider.objects.get_or_create(
    name="avatar-picker-proxy",
    defaults={"mode": ProxyMode.FORWARD_SINGLE, "external_host": "https://avatars.holy-grail.ch",
              "authorization_flow": src.authorization_flow,
              "invalidation_flow": src.invalidation_flow},
)
Application.objects.get_or_create(
    slug="avatar-picker",
    defaults={"name": "Avatar picker", "provider": prov,
              "meta_launch_url": "https://avatars.holy-grail.ch"},
)
op = Outpost.objects.get(name="authentik Embedded Outpost")
op.providers.add(prov)
op.save()

# 4. avatar source: picker choice first, initials fallback (drops gravatar)
t = Tenant.objects.get(schema_name="public")
t.avatars = "attributes.avatar,initials"
t.save()

print("TOKEN=" + tok.key)
