#!/usr/bin/env bash
# Builds $NOTES_DIR (private, outside this repo) into $NOTES_DIR/www with the Wiki's pinned MkDocs Material image (non-root, no capabilities, strict).
set -euo pipefail
cd "$(dirname "$0")"
NOTES_DIR=$(sed -n 's/^NOTES_DIR=//p' .env)
IMAGE=$(sed -n 's/^IMAGE=//p' ../Wiki/build.sh)
UID_GID=65059:65059
mkdir -p "$NOTES_DIR/www"
[ "$(stat -c %u "$NOTES_DIR/www")" = 65059 ] || sudo chown 65059:1000 "$NOTES_DIR/www"
docker run --rm --user "$UID_GID" --cap-drop ALL --security-opt no-new-privileges:true \
  --read-only --tmpfs /tmp \
  -v "$NOTES_DIR:/docs:ro" -v "$NOTES_DIR/www:/out" \
  --entrypoint mkdocs "$IMAGE" build --strict --clean -f /docs/mkdocs.yml -d /out
