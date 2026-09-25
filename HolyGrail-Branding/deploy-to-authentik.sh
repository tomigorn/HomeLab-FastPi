#!/usr/bin/env bash
# Re-point authentik at the current contents of ./icons.
#
# Run this after changing anything in icons/. Must be run with sudo: the store and
# authentik's media directory are both read-only by design.
#
#   sudo /home/pi/Projects/HolyGrail-Branding/deploy-to-authentik.sh
#
# Why a script rather than "the symlink picks it up automatically":
#
#   The symlinks DO pick up new bytes instantly - that part is automatic. But the
#   login-page logo is served through Cloudflare with cache-control max-age=14400,
#   so for four hours the edge keeps returning the OLD image under the same URL.
#   The filenames therefore embed the file's md5 prefix: new content = new URL =
#   cache bypassed. This script recomputes those names and updates the Brand.
#
#   The EMAIL logo needs no renaming (it is attached to each message, not fetched)
#   but logo_data() is lru_cached, so the containers must be restarted.
set -euo pipefail
STORE=/home/pi/Projects/HolyGrail-Branding/icons
MEDIA=/home/pi/Projects/Docker/Authentik/data/media/public

[ -r "$STORE/logo-1024.png" ] || { echo "missing $STORE/logo-1024.png" >&2; exit 1; }
[ -r "$STORE/favicon.svg"   ] || { echo "missing $STORE/favicon.svg" >&2; exit 1; }

LH=$(md5sum "$STORE/logo-1024.png" | cut -c1-8)
FH=$(md5sum "$STORE/favicon.svg"   | cut -c1-8)
LOGO="holy-grail-logo-$LH.png"
FAV="holy-grail-icon-$FH.svg"

chmod 755 "$MEDIA"
rm -f "$MEDIA"/*
ln -s "$STORE/logo-1024.png" "$MEDIA/$LOGO"
ln -s "$STORE/favicon.svg"   "$MEDIA/$FAV"
chmod 555 "$MEDIA"
echo "symlinked: $LOGO  $FAV"

docker exec -i authentik-server ak shell -c "
from authentik.brands.models import Brand
b = Brand.objects.get(default=True)
b.branding_logo = '$LOGO'
b.branding_favicon = '$FAV'
b.save()
print('brand updated ->', b.branding_logo, b.branding_favicon)" 2>/dev/null | tail -1

echo "restarting containers (logo_data() is lru_cached)..."
docker restart authentik-server authentik-worker >/dev/null
echo "done. NOTE: docker cp'd blueprints survive a restart but NOT a --force-recreate."
