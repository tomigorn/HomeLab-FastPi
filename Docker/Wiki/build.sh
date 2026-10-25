#!/usr/bin/env bash
# Builds site/ into www/ with the pinned MkDocs Material image (non-root, no capabilities, strict).
set -euo pipefail
cd "$(dirname "$0")"
IMAGE=squidfunk/mkdocs-material:9.8.0
UID_GID=65053:65053
mkdir -p www
[ "$(stat -c %u www)" = 65053 ] || sudo chown 65053:1000 www
docker run --rm --user "$UID_GID" --cap-drop ALL --security-opt no-new-privileges:true \
  --read-only --tmpfs /tmp \
  -v "$PWD/site:/docs:ro" -v "$PWD/www:/out" \
  --entrypoint mkdocs "$IMAGE" build --strict --clean -f /docs/mkdocs.yml -d /out
