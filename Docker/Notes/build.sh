#!/usr/bin/env bash
# Builds $NOTES_DIR (private, outside this repo) into $NOTES_DIR/www with the Wiki's pinned MkDocs Material image (non-root, no capabilities, strict).
set -euo pipefail
cd "$(dirname "$0")"
NOTES_DIR=$(sed -n 's/^NOTES_DIR=//p' .env)
IMAGE=$(sed -n 's/^IMAGE=//p' ../Wiki/build.sh)
UID_GID=65059:65059
# Recently changed: one row per page from git history (first commit = added, last commit = updated), newest first.
{ printf '# Recently changed\n\nNewest first, from the notes history. New pages are marked 🆕.\n\n| Date | Page | |\n|---|---|---|\n'
  for f in "$NOTES_DIR"/docs/*.md; do b=$(basename "$f"); case $b in index.md|recent.md|chapter-*) continue;; esac
    last=$(git -C "$NOTES_DIR" log -1 --format=%cs -- "docs/$b"); first=$(git -C "$NOTES_DIR" log --diff-filter=A --format=%cs -- "docs/$b" | tail -1)
    [ -n "$last" ] || continue; title=$(sed -n 's/^# //p' "$f" | head -1)
    printf '%s|| %s | [%s](%s) | %s |\n' "$last" "$last" "${title:-$b}" "$b" "$([ "$first" = "$last" ] && echo 🆕 new || echo updated)"
  done | sort -r | head -20 | cut -d'|' -f3- | sed 's/^/|/'; } > "$NOTES_DIR/docs/recent.md"
mkdir -p "$NOTES_DIR/www"
[ "$(stat -c %u "$NOTES_DIR/www")" = 65059 ] || sudo chown 65059:1000 "$NOTES_DIR/www"
docker run --rm --user "$UID_GID" --cap-drop ALL --security-opt no-new-privileges:true \
  --read-only --tmpfs /tmp \
  -v "$NOTES_DIR:/docs:ro" -v "$NOTES_DIR/www:/out" \
  --entrypoint mkdocs "$IMAGE" build --strict --clean -f /docs/mkdocs.yml -d /out
