# Idempotent look of the user "Application Dashboard" (sso.holy-grail.ch/if/user/#/library):
# sections, icons, descriptions, new tab, hidden helper apps, navy/gold theme.
#
# Run (after scripts/fetch-app-icons.sh has put the icons in place):
#   cd Docker/Authentik && docker compose exec -T server ak shell < scripts/dashboard-look.py
#
# Touches ONLY look fields: Application.group / meta_description / meta_publisher (cleared) /
# meta_icon / open_in_new_tab / meta_hide, and on the default Brand
# branding_custom_css. Names, providers, launch URLs, policy bindings (who sees what),
# flows and footer links are left alone, so this never conflicts with
# provision-admin-sso.py or the Avatar-Picker provisioning.
import glob
import os

from authentik.brands.models import Brand
from authentik.core.models import Application

ICON_DIR = "/data/media/public"  # = Docker/Authentik/data/media/public on the host

# slug: (section, description, icon)
#   description: a short noun phrase; an optional second line (after "\n") is the wake
#   note for apps that wake a sleeping host, shown under the caption and in the menu.
#   icon: None = apps/<slug>-*.svg from fetch-app-icons.sh (downloaded, or bundled in
#   icons/), otherwise a literal meta_icon value (fa://, https://, /static/...).
# Sections sort A to Z in authentik; the custom CSS below orders them Media, Downloads, Account, Homelab.
BEEFY = "\nwakes Beefy · ~55 s"
TOWER = "\nwakes Tower · ~110 s"
APPS = {
    "jellyfin":          ("Media", "Film & series streaming" + BEEFY, None),
    "requests":          ("Media", "Request films & series" + BEEFY, None),
    "audiobookshelf":    ("Media", "Audiobook streaming", None),
    "nextcloud":         ("Media", "Files & calendar" + TOWER, None),
    "radarr":            ("Downloads", "Film downloads" + BEEFY, None),
    "sonarr":            ("Downloads", "Series downloads" + BEEFY, None),
    "prowlarr":          ("Downloads", "Indexer manager" + BEEFY, None),
    "sabnzbd":           ("Downloads", "Usenet downloader" + BEEFY, None),
    "qbittorrent":       ("Downloads", "Torrent downloader" + BEEFY, None),
    "bazarr":            ("Downloads", "Subtitles" + BEEFY, None),
    "grafana":           ("Homelab", "Dashboards & metrics", None),
    "portainer":         ("Homelab", "Docker management", None),
    "adguard":           ("Homelab", "DNS & ad blocking", None),
    "traefik-dashboard": ("Homelab", "Reverse proxy", None),
    "wg-easy":           ("Homelab", "VPN clients", None),
    "home-assistant":    ("Homelab", "Smart home", None),
    "cup":               ("Homelab", "Container updates", None),
    "claude-mockups":    ("Homelab", "UI mockups", "fa://fa-palette"),
    "avatar-picker":     ("Account", "Your profile picture", None),
}

# Technical helpers: hidden from the dashboard with meta_hide. Their providers,
# launch URLs and bindings are untouched, so the wake-on-sign-in flows keep working.
HIDDEN = ["jellyfin-wake", "nextcloud-wake", "requests-login"]

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
/* meta_description may hold one newline: the wake note goes on its own line, in the
   caption and in the open menu. */
[part="card-header-action-description"] { white-space: pre-line; }

@media (min-width: 768px) {
[part="app-list"]:not([data-view-mode="list"]) [part="card-wrapper"] { --hg-caption-height: 2.4rem; }
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
  height: var(--hg-caption-height);
  transform: none;
  width: auto; min-width: 0; max-width: none;
  margin: 0; padding: 0 .4rem;
  overflow: hidden;
  background: transparent; box-shadow: none; filter: none; border: none;
  pointer-events: none;
  text-align: center;
}
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="anchor-position"] [part="card-header-actions-menu"]:not(:popover-open) [part="card-header-action"],
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="fallback"] [part="card-header-actions"]:not(:focus-within) [part="card-header-actions-menu"] [part="card-header-action"] {
  padding: 0; background: transparent; text-align: center;
}
/* Caption: title font, line 1 = description, line 2 = wake note (dimmer). The template
   wraps the text in newlines, so pre-line renders a blank first line (CSS 2.1 10.8: a line
   ending in a preserved newline keeps its height); a margin of exactly -1lh pulls it out
   of the fixed-height caption (calc = fallback for browsers without lh). That blank line
   takes ::first-line, so the note is dimmed with a gradient clipped to the text instead:
   the split sits on the boundary between line 2 and 3 of the box. */
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="anchor-position"] [part="card-header-actions-menu"]:not(:popover-open) [part="card-header-action-description"],
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="fallback"] [part="card-header-actions"]:not(:focus-within) [part="card-header-actions-menu"] [part="card-header-action-description"] {
  --hg-caption-line: calc(1.4 * .74rem);
  --hg-caption-line: 1lh;
  display: block;
  margin: calc(-1 * var(--hg-caption-line)) 0 0;
  font-family: var(--pf-global--FontFamily--heading--sans-serif);
  font-size: .74rem; line-height: 1.4; font-weight: 500;
  color: var(--hg-caption-color, var(--pf-global--Color--100));
  text-wrap: pretty;
}
@supports (-webkit-background-clip: text) or (background-clip: text) {
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="anchor-position"] [part="card-header-actions-menu"]:not(:popover-open) [part="card-header-action-description"],
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="fallback"] [part="card-header-actions"]:not(:focus-within) [part="card-header-actions-menu"] [part="card-header-action-description"] {
  background: linear-gradient(var(--hg-caption-color, var(--pf-global--Color--100)) 0 calc(2 * var(--hg-caption-line)),
                              var(--hg-caption-note-color, var(--pf-global--Color--200)) calc(2 * var(--hg-caption-line)) 100%);
  -webkit-background-clip: text; background-clip: text;
  color: transparent;
}
}
[part="app-list"]:not([data-view-mode="list"]) [part="card-wrapper"] {
  --hg-caption-color: var(--pf-global--Color--200);
  --hg-caption-note-color: color-mix(in srgb, var(--pf-global--Color--200) 70%, transparent);
}
:host([theme="dark"]) [part="app-list"]:not([data-view-mode="list"]) [part="card-wrapper"] {
  --hg-caption-color: #aeb9cf;
  --hg-caption-note-color: #7c89a6;
}
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="anchor-position"] [part="card-header-actions-menu"]:not(:popover-open) :is([part="card-header-action-publisher"], ak-divider, li:has(> a)),
[part="app-list"]:not([data-view-mode="list"])[data-anchor-strategy="fallback"] [part="card-header-actions"]:not(:focus-within) [part="card-header-actions-menu"] :is([part="card-header-action-publisher"], ak-divider, li:has(> a)) {
  display: none;
}
}

/* List view (authentik switches to it under 768 px, so this is the phone layout).
   The row text is one string "description · publisher" with the wake note after a
   newline: pre-line puts the note on its own line, publisher last. The template leaves
   a newline before the text, which pre-line renders as a blank first line (CSS 2.1
   10.8: a line ending in a preserved newline keeps its height); the negative margin
   of exactly one line hides it (lh where supported, the calc mirrors the stock
   font-size and line-height of .row-meta). */
[part="app-list"][data-view-mode="list"] [part="row-meta"] {
  white-space: pre-line;
  margin-top: calc(-1.3 * var(--pf-global--FontSize--sm));
  margin-top: -1lh;
}

/* Section order, grid and list (sections otherwise sort A-Z):
   Media, Downloads, Account, Homelab (infrastructure admin tools) last.
   The list container is display:block in authentik, so make it a flex column for order. */
[part="app-list"][data-view-mode="list"][data-anchor-strategy] { display: flex; flex-direction: column; }
[part="app-list"] [data-group-id="media"] { order: -2; }
[part="app-list"] [data-group-id="downloads"] { order: -1; }
[part="app-list"] [data-group-id="homelab"] { order: 99; }
"""


def icon_for(slug, literal):
    if literal:
        return literal
    found = sorted(glob.glob(os.path.join(ICON_DIR, "apps", f"{slug}-*.svg")))
    if not found:
        return None  # leave the current icon alone
    return os.path.relpath(found[-1], ICON_DIR)  # e.g. apps/jellyfin-4ebae366.svg


for slug, (group, desc, literal) in APPS.items():
    fields = {"group": group, "meta_description": desc, "meta_publisher": "",
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
