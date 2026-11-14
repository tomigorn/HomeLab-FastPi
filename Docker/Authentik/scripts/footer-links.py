# Footer links on every flow page (login, invite sign-up, TOTP setup, recovery). Idempotent.
# Run: docker exec -i authentik-server ak shell < scripts/footer-links.py
# footer_links lives on the Tenant, which blueprints cannot manage, hence a script.
from authentik.tenants.models import Tenant

LINKS = [
    {"name": "holy-grail.ch", "href": "https://holy-grail.ch"},
    {"name": "Help: create your account", "href": "https://wiki.holy-grail.ch/getting-started/"},
    {"name": "powered by authentik", "href": "https://goauthentik.io"},
]

t = Tenant.objects.get(schema_name="public")
if t.footer_links != LINKS:
    t.footer_links = LINKS
    t.save()
    print("footer_links updated")
else:
    print("footer_links unchanged")
