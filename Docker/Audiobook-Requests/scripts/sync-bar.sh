#!/usr/bin/env bash
# sync-bar.sh [--check]: the shared bar's vendored copy from the canonical one (beefy, HomeLab-BeefyServer HEAD, README "Requests bar").
# Default copies; --check compares sha256: exit 0 same, 1 differs, 3 beefy not reachable (never woken: ssh beefy-direct, one try).
set -uo pipefail
ABR=${ABR_DIR:-$(cd "$(dirname "$0")/.." && pwd)}
FILES=("indexer-bar/www/bar.js:books-proxy/www/bar/bar.js" "indexer-bar/www/bar.css:books-proxy/www/bar/bar.css" "indexer-bar/schema.md:abr-bar/indexer-bar-schema.md")
remote() { ssh -o BatchMode=yes -o ConnectTimeout=5 -o ConnectionAttempts=1 beefy-direct "git -C Projects show HEAD:Docker/Seerr/$1"; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
for f in "${FILES[@]}"; do
  src=${f%%:*}
  remote "$src" > "$tmp/$(basename "$src")" 2>/dev/null || { echo "skipped: beefy not reachable (not woken)"; exit 3; }
done
diff=()
for f in "${FILES[@]}"; do
  src=${f%%:*} dst=$ABR/${f#*:}
  [[ $(sha256sum < "$tmp/$(basename "$src")") == $( { sha256sum < "$dst"; } 2>/dev/null) ]] || diff+=("$(basename "$dst")")
done
if [[ ${1:-} == --check ]]; then
  (( ${#diff[@]} == 0 )) && { echo same; exit 0; }
  echo "differs: ${diff[*]}"; exit 1
fi
for f in "${FILES[@]}"; do src=${f%%:*}; install -m 0644 "$tmp/$(basename "$src")" "$ABR/${f#*:}"; done
echo "copied: ${diff[*]:-nothing changed}"
