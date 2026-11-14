#!/usr/bin/env bash
# Builds site/ into www/ and site-admin/ into www-admin/ with the pinned MkDocs Material image (non-root, no capabilities, strict).
set -euo pipefail
cd "$(dirname "$0")"
IMAGE=squidfunk/mkdocs-material:9.8.0
UID_GID=65053:65053
for pair in site:www site-admin:www-admin; do
  src=${pair%%:*}; out=${pair##*:}
  mkdir -p "$out"
  [ "$(stat -c %u "$out")" = 65053 ] || sudo chown 65053:1000 "$out"
  docker run --rm --user "$UID_GID" --cap-drop ALL --security-opt no-new-privileges:true \
    --read-only --tmpfs /tmp \
    -v "$PWD/$src:/docs:ro" -v "$PWD/$out:/out" \
    --entrypoint mkdocs "$IMAGE" build --strict --clean -f /docs/mkdocs.yml -d /out
done
