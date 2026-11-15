#!/usr/bin/env bash
# Against the running books-proxy: every icon URL serves our file (www/icons) with the right type, never ABR's original.
set -uo pipefail
ICONS=$(cd "$(dirname "$0")/../www/icons" && pwd)
BP=http://127.0.0.1:8080
fail=0
hdr=$(mktemp); trap 'rm -f "$hdr"' EXIT
ok() { echo "  ok   $1"; }
bad() { echo "  FAIL $1"; fail=1; }

while read -r path file type abr; do
  got=$(docker exec books-proxy curl -s -m 5 -D /dev/stderr "$BP$path?v=test" 2>"$hdr" | sha256sum | cut -d' ' -f1)
  ctype=$(grep -i '^content-type:' "$hdr" | tr -d '\r' | cut -d' ' -f2)
  status=$(head -1 "$hdr" | cut -d' ' -f2)
  [[ $status == 200 ]] && ok "$path 200" || bad "$path status $status"
  [[ $got == "$(sha256sum < "$ICONS/$file" | cut -d' ' -f1)" ]] && ok "$path = icons/$file" || bad "$path is not icons/$file"
  [[ $ctype == "$type" ]] && ok "$path $ctype" || bad "$path content type $ctype, want $type"
  if [[ $abr != - ]]; then
    [[ $got != "$(docker exec audiobookrequest cat "/app/static/$abr" | sha256sum | cut -d' ' -f1)" ]] && ok "$path not ABR's" || bad "$path still ABR's $abr"
  fi
done <<'EOF'
/static/favicon.svg favicon.svg image/svg+xml favicon.svg
/static/favicon-32x32.png favicon-32x32.png image/png favicon-32x32.png
/static/favicon-16x16.png favicon-16x16.png image/png favicon-16x16.png
/static/apple-touch-icon.png apple-touch-icon.png image/png apple-touch-icon.png
/static/site.webmanifest site.webmanifest application/manifest+json site.webmanifest
/favicon.ico favicon.ico image/x-icon -
/_hg/icons/android-chrome-192x192.png android-chrome-192x192.png image/png -
/_hg/icons/android-chrome-512x512.png android-chrome-512x512.png image/png -
EOF

links=$(docker exec books-proxy curl -s -m 5 "$BP/auth/login?backup=1" | tr '\n' ' ' | grep -oE '<link[^>]*rel="(icon|apple-touch-icon|manifest)"[^>]*>' | grep -oE 'href="[^"?]*' | cut -d'"' -f2 | sort | xargs)
want="/static/apple-touch-icon.png /static/favicon-16x16.png /static/favicon-32x32.png /static/favicon.svg /static/site.webmanifest"
[[ $links == "$want" ]] && ok "page icon links all overridden" || bad "page icon links changed: $links"

((fail == 0)) && echo "icons-live: all passed" || { echo "icons-live: FAILED"; exit 1; }
