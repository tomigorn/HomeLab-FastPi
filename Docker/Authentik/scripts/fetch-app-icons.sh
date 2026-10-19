#!/usr/bin/env bash
# Download the application dashboard icons into authentik's media store.
#
#   cd Docker/Authentik && ./scripts/fetch-app-icons.sh
#   docker compose exec -T server ak shell < scripts/dashboard-look.py
#
# Icons come from homarr-labs/dashboard-icons (Apache-2.0) at a PINNED commit.
# The logos remain their owners' trademarks; they are used to identify the apps
# on a private dashboard. They are NOT committed (this repo is public): only
# this script and the icon list below are tracked. data/ is gitignored.
# Our own icons (icons/<slug>.svg in this project, Holy Grail style) are
# committed and installed the same way.
#
# All files land as data/media/public/apps/<slug>-<md5-8>.svg. The content hash in
# the name is deliberate: sso.holy-grail.ch sits behind Cloudflare, which caches
# media for 4 hours, so new artwork must mean a new URL. dashboard-look.py finds
# each icon by globbing apps/<slug>-*.svg. Idempotent: re-running with the same
# commit changes nothing; stale versions of a slug's icon are removed.
set -euo pipefail

COMMIT=6d31345986eba2067a63eb41c1a5a87d4e8e850a
BASE="https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons@${COMMIT}/svg"
UA="homelab-icon-fetch/1.0"

# authentik application slug -> dashboard-icons name
ICONS=(
  "adguard:adguard-home"
  "audiobookshelf:audiobookshelf"
  "bazarr:bazarr"
  "cup:cup"
  "grafana:grafana"
  "home-assistant:home-assistant"
  "jellyfin:jellyfin"
  "nextcloud:nextcloud"
  "portainer:portainer"
  "prowlarr:prowlarr"
  "qbittorrent:qbittorrent"
  "radarr:radarr"
  "requests:seerr"
  "sabnzbd:sabnzbd"
  "sonarr:sonarr"
  "traefik-dashboard:traefik"
  "wg-easy:wireguard"
)

HERE="$(cd "$(dirname "$0")/.." && pwd)"
PUBLIC="$HERE/data/media/public"
DEST="$PUBLIC/apps"

# data/media/public is kept read-only (it holds the branding symlinks). Open it
# just long enough to create apps/ once, and restore the mode whatever happens.
if [ ! -d "$DEST" ]; then
  mode=$(stat -c '%a' "$PUBLIC")
  chmod u+w "$PUBLIC"
  trap 'chmod "$mode" "$PUBLIC"' EXIT
  mkdir "$DEST"
  chmod "$mode" "$PUBLIC"
  trap - EXIT
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# install <slug> <file>: put the file in place under its hashed name, drop old versions.
install_icon() {
  local slug=$1 file=$2 hash target
  # Refuse anything that is not an SVG document.
  if ! head -c 512 "$file" | grep -qi '<svg\|<?xml'; then
    echo "ERROR: $file is not an SVG" >&2
    exit 1
  fi
  hash=$(md5sum "$file" | cut -c1-8)
  target="$DEST/$slug-$hash.svg"
  if [ -f "$target" ]; then
    echo "unchanged  apps/$slug-$hash.svg"
  else
    install -m 444 "$file" "$target"
    echo "new        apps/$slug-$hash.svg"
  fi
  find "$DEST" -maxdepth 1 -name "$slug-*.svg" ! -name "$slug-$hash.svg" -delete
}

for pair in "${ICONS[@]}"; do
  slug=${pair%%:*}
  name=${pair#*:}
  curl -fsSL --retry 3 -A "$UA" -o "$tmp/$slug.svg" "$BASE/$name.svg"
  install_icon "$slug" "$tmp/$slug.svg"
done

for file in "$HERE"/icons/*.svg; do
  install_icon "$(basename "$file" .svg)" "$file"
done
