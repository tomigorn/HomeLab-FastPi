# Idempotent look of the user "Application Dashboard" (sso.holy-grail.ch/if/user/#/library):
# sections, icons, descriptions, new tab, hidden helper apps, navy/gold theme.
#
# Run (after scripts/fetch-app-icons.sh has put the icons in place):
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/dashboard-look.py
#
# Touches ONLY look fields: Application.group / meta_description / meta_publisher /
# meta_icon / open_in_new_tab / meta_hide, and on the default Brand
# branding_custom_css. Names, providers, launch URLs, policy bindings (who sees what),
# flows and footer links are left alone, so this never conflicts with
# provision-admin-sso.py or the Avatar-Picker provisioning.
import glob
import os

from authentik.brands.models import Brand
from authentik.core.models import Application

ICON_DIR = "/data/media/public"  # = Docker/Authentik/data/media/public on the host

# slug: (section, description, publisher, icon)
#   icon: None = apps/<slug>-*.svg from fetch-app-icons.sh, otherwise a literal
#   meta_icon value (fa://, https://, /static/...).
# Sections sort A to Z in authentik; the custom CSS below pulls Media to the top.
APPS = {
    "jellyfin":          ("Media", "Films & series (wakes Beefy, ~45 s)", "Jellyfin", None),
    "requests":          ("Media", "Request films & series (wakes Beefy, ~45 s)", "Seerr", None),
    "audiobookshelf":    ("Media", "Audiobooks & podcasts", "Audiobookshelf", None),
    "nextcloud":         ("Media", "Files, photos & calendar", "Nextcloud", None),
    "radarr":            ("Downloads", "Film manager", "Servarr", None),
    "sonarr":            ("Downloads", "Series manager", "Servarr", None),
    "prowlarr":          ("Downloads", "Indexer manager", "Servarr", None),
    "sabnzbd":           ("Downloads", "Usenet downloader", "SABnzbd", None),
    "qbittorrent":       ("Downloads", "Torrent client", "qBittorrent", None),
    "bazarr":            ("Downloads", "Subtitles", "Bazarr", None),
    "grafana":           ("Homelab", "Dashboards & metrics", "Grafana Labs", None),
    "portainer":         ("Homelab", "Docker management", "Portainer", None),
    "adguard":           ("Homelab", "DNS & ad blocking", "AdGuard", None),
    "traefik-dashboard": ("Homelab", "Reverse proxy routes", "Traefik Labs", None),
    "wg-easy":           ("Homelab", "WireGuard VPN clients", "wg-easy", None),
    "home-assistant":    ("Homelab", "Smart home", "Home Assistant", None),
    "cup":               ("Homelab", "Container image updates", "Cup", None),
    "claude-mockups":    ("Homelab", "UI mockups & demos", "Holy Grail", "fa://fa-palette"),
    "avatar-picker":     ("Account", "Choose your profile picture", "Holy Grail", "fa://fa-user-circle"),
}

# Technical helpers: hidden from the dashboard with meta_hide. Their providers,
# launch URLs and bindings are untouched, so the wake-on-sign-in flows keep working.
HIDDEN = ["jellyfin-wake", "nextcloud-wake"]

# Brand custom CSS. authentik adopts it into EVERY component's shadow root (login and
# recovery flows included), so every rule is scoped to the library page's own parts
# and to dark theme. It relies on UNDOCUMENTED internal selectors ([part=...],
# data-group-id, theme attribute) read from the 2026.8.4 source - re-check after an
# authentik upgrade. Safe-mode sessions (recovery links) get no custom CSS at all.
CUSTOM_CSS = """\
/* Holy Grail dashboard look - managed by Docker/Authentik/scripts/dashboard-look.py */

/* Navy page background with a soft chalice-gold glow (user interface, dark theme only;
   done here instead of settings.theme.background, which would also apply in light mode) */
:host([theme="dark"]) [part="background-wrapper"] {
  background: radial-gradient(1200px 520px at 85% -10%, rgba(233, 185, 73, .16), transparent 60%),
              linear-gradient(180deg, #0b1628, #0a1220 60%, #080d18);
}
:host([theme="dark"]) [part="background-default-slant"] { display: none; }

/* Navy app tiles to match (dark theme only) */
:host([theme="dark"]) [part="app-list"] [part="card"] {
  --pf-c-card--BackgroundColor: #13223a;
  border-color: #24395c;
}

/* Gold hover ring on app tiles */
[part="app-list"] [part="card"]:hover {
  border-color: #e9b949;
  box-shadow: 0 0 0 1px #e9b949, 0 8px 22px rgba(233, 185, 73, .18);
}

/* Gold section titles */
:host([theme="dark"]) [part="app-group-header"] h2 { color: #ffe7a3; }

/* Description under the tile name (grid view, desktop widths). authentik 2026.8 renders
   meta_description only inside the tile's "⋮" popover menu; this shows that menu's CLOSED
   state in-flow as a caption and leaves the open menu (publisher, Edit for admins) alone.
   Phones keep the stock compact tile. Selectors from the 2026.8.4 LibraryApplication source. */
@media (min-width: 768px) {
[part="app-list"]:not([data-view-mode="list"]) [part="card-wrapper"] { --hg-caption-height: 2.1rem; }
[part="app-list"]:not([data-view-mode="list"]) .card-header-aspect-wrapper {
  inset-block-end: var(--hg-caption-height);
  height: auto;
}
[part="app-list"]:not([data-view-mode="list"]) [part="card"] ak-app-icon { --icon-height: 44%; }
[part="app-list"]:not([data-view-mode="list"]) [part="card"] ak-app-icon::part(icon) {
  inset-block-start: .5rem;
  inset-block-end: calc(var(--hg-caption-height) + 1.2rem);
}
[part="app-list"]:not([data-view-mode="list"]) [part="card-title"] { align-items: flex-end; }
[part="app-list"]:not([data-view-mode="list"]) [part="card-header-actions"] {
  inset: 0;
  pointer-events: none;
}
[part="app-list"]:not([data-view-mode="list"]) [part="card-header-actions-button"] {
  position: absolute;
  inset-block-start: 0;
  inset-inline-end: 0;
  pointer-events: auto;
}
[part="app-list"]:not([data-view-mode="list"]) [part="card-header-actions-menu"] { pointer-events: auto; }
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="anchor-position"] [part="card-header-actions-menu"]:not(:popover-open),
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="fallback"] [part="card-header-actions"]:not(:focus-within) [part="card-header-actions-menu"] {
  display: block;
  position: absolute;
  inset: auto 0 0 0;
  transform: none;
  width: auto; min-width: 0; max-width: none;
  margin: 0; padding: 0 .5rem .4rem;
  background: transparent; box-shadow: none; filter: none; border: none;
  pointer-events: none;
  font-size: .72rem; line-height: 1.2; text-align: center;
  color: var(--pf-global--Color--200);
}
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="anchor-position"] [part="card-header-actions-menu"]:not(:popover-open) [part="card-header-action"],
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="fallback"] [part="card-header-actions"]:not(:focus-within) [part="card-header-actions-menu"] [part="card-header-action"] {
  padding: 0; background: transparent; white-space: normal; text-align: center; color: inherit; font-size: inherit; line-height: inherit;
}
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="anchor-position"] [part="card-header-actions-menu"]:not(:popover-open) [part="card-header-action-description"],
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="fallback"] [part="card-header-actions"]:not(:focus-within) [part="card-header-actions-menu"] [part="card-header-action-description"] {
  margin: 0; font-size: inherit; line-height: inherit;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="anchor-position"] [part="card-header-actions-menu"]:not(:popover-open) :is([part="card-header-action-publisher"], ak-divider, li:has(> a)),
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="fallback"] [part="card-header-actions"]:not(:focus-within) [part="card-header-actions-menu"] :is([part="card-header-action-publisher"], ak-divider, li:has(> a)) {
  display: none;
}
}

/* Section order (sections otherwise sort A-Z; grid view only):
   Media first, Homelab (infrastructure admin tools) last. */
[part="app-list"] [data-group-id="media"] { order: -1; }
[part="app-list"] [data-group-id="homelab"] { order: 99; }
"""


def icon_for(slug, literal):
    if literal:
        return literal
    found = sorted(glob.glob(os.path.join(ICON_DIR, "apps", f"{slug}-*.svg")))
    if not found:
        return None  # leave the current icon alone
    return os.path.relpath(found[-1], ICON_DIR)  # e.g. apps/jellyfin-4ebae366.svg


for slug, (group, desc, publisher, literal) in APPS.items():
    fields = {"group": group, "meta_description": desc, "meta_publisher": publisher,
              "open_in_new_tab": True, "meta_hide": False}
    icon = icon_for(slug, literal)
    if icon:
        fields["meta_icon"] = icon
    else:
        print(f"WARN no icon file for {slug} - run scripts/fetch-app-icons.sh")
    if Application.objects.filter(slug=slug).update(**fields) == 0:
        print(f"WARN application {slug} not found")
    else:
        print(f"ok   {slug}")

for slug in HIDDEN:
    if Application.objects.filter(slug=slug).update(meta_hide=True) == 0:
        print(f"WARN application {slug} not found")
    else:
        print(f"ok   {slug} (hidden)")

known = set(APPS) | set(HIDDEN)
for slug in Application.objects.exclude(slug__in=known).values_list("slug", flat=True):
    print(f"NOTE {slug} is not managed here - add it to APPS")

brand = Brand.objects.get(default=True)
if brand.branding_custom_css != CUSTOM_CSS:
    Brand.objects.filter(pk=brand.pk).update(branding_custom_css=CUSTOM_CSS)
    print("ok   brand custom CSS updated")
else:
    print("ok   brand custom CSS unchanged")

# authentik caches each user's application list; .update() fires no signals, so clear
# it the same way authentik's own post_save handler does.
from django.core.cache import cache  # noqa: E402

from authentik.core.api.applications import user_app_cache_key  # noqa: E402

cache.delete_many(cache.keys(user_app_cache_key("*")) or [])
print("ok   application list cache cleared")
