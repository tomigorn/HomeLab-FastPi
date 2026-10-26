#!/usr/bin/env bash
# Writes overlay/BaseLayout.jinja = the image's own navbar template plus one "Movies / Series" link to Seerr. Rerun after every ABR image bump (compose mounts the file read-only).
#   bash Docker/Audiobook-Requests/scripts/build-overlay.sh && docker compose up -d abr
set -euo pipefail
cd "$(dirname "$0")/.."
image=$(sed -n 's/^    image: \(markbeep\/audiobookrequest:.*\)$/\1/p' docker-compose.yaml)
cid=$(docker create "$image")
trap 'docker rm -f "$cid" >/dev/null' EXIT
docker cp "$cid:/app/templates/layouts/BaseLayout.jinja" overlay/BaseLayout.jinja.orig
python3 - <<'PY'
from pathlib import Path
src = Path("overlay/BaseLayout.jinja.orig").read_text()
marker = 'title="Wishlist">'
anchor_end = src.find("</a>", src.find(marker))
if src.count(marker) != 1 or anchor_end < 0:
    raise SystemExit("navbar marker not found: check the template of this ABR version")
link = '''
                        <a href="https://requests.holy-grail.ch/" class="btn btn-ghost" title="Movies / Series">Movies / Series</a>'''
out = src[:anchor_end + 4] + link + src[anchor_end + 4:]
Path("overlay/BaseLayout.jinja").write_text(out)
print("overlay/BaseLayout.jinja written")
PY
rm overlay/BaseLayout.jinja.orig
