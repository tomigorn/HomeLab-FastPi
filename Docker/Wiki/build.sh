#!/usr/bin/env bash
# Builds site/ into one www/<variant>/ per permission level and site-admin/ into www-admin/ with the pinned MkDocs Material image (non-root, no capabilities, strict).
set -euo pipefail
cd "$(dirname "$0")"
IMAGE=squidfunk/mkdocs-material:9.8.0
UID_GID=65053:65053
# Groups that hide pages or parts (front matter `groups:`, `<!-- only: … -->`), sorted; each needs a map in the Caddyfile.
GATES=(streaming-requesters)

mkdocs() { # $1 source, $2 output mount, $3 dir inside it, $4 groups of this build
  docker run --rm --user "$UID_GID" --cap-drop ALL --security-opt no-new-privileges:true \
    --read-only --tmpfs /tmp \
    -e WIKI_GATES="$(IFS=,; echo "${GATES[*]}")" -e WIKI_GROUPS="$4" \
    -v "$PWD/$1:/docs:ro" -v "$PWD/$2:/out" \
    --entrypoint mkdocs "$IMAGE" build --strict --clean -f /docs/mkdocs.yml -d "/out/$3"
}

for out in www www-admin; do
  mkdir -p "$out"
  [ "$(stat -c %u "$out")" = 65053 ] || sudo chown 65053:1000 "$out"
done

variants=()
for ((mask = 0; mask < 1 << ${#GATES[@]}; mask++)); do
  name=base groups=()
  for i in "${!GATES[@]}"; do
    if ((mask >> i & 1)); then name+="+${GATES[i]}"; groups+=("${GATES[i]}"); fi
  done
  variants+=("$name")
  echo "== $name"
  mkdocs site www "$name" "$(IFS=,; echo "${groups[*]}")"
done
mkdocs site-admin www-admin "" ""

# Remove what no variant owns any more (old flat build, dropped gates).
docker run --rm --user "$UID_GID" --cap-drop ALL --security-opt no-new-privileges:true --read-only \
  -v "$PWD/www:/out" --entrypoint sh "$IMAGE" -c \
  'cd /out && for f in * .[!.]*; do [ -e "$f" ] || continue; case " $* " in *" $f "*) ;; *) rm -rf -- "$f";; esac; done' sh "${variants[@]}"
