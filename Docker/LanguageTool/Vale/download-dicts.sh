#!/usr/bin/env bash
# =========================================================
# download-dicts.sh — fetch Hunspell dictionaries for the "spelling floor"
# =========================================================
# Pulls the CURRENT dictionaries straight from the upstream LibreOffice
# dictionaries repo (master):
#   * en_GB       — British English   -> used by Vale's English speller
#   * de_CH_frami — the real Swiss German dict (igerman98 / Franz Michael
#                   Baumann "frami"), NOT de-DE with ß stripped. Placed
#                   here for LibreOffice / LaTeX / reference use. Vale does
#                   NOT spell-check German (compounding); LanguageTool
#                   already ships this same frami dict internally.
#
# Files land in ./dicts (gitignored — re-downloadable). Vale reads them
# via `dicpath: ../dicts` in styles/HouseStyle/Spelling.yml.
# =========================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DICTS="$SCRIPT_DIR/dicts"
VOCAB="$SCRIPT_DIR/styles/config/vocabularies/House"
BASE="https://raw.githubusercontent.com/LibreOffice/dictionaries/master"

mkdir -p "$DICTS" "$VOCAB"

fetch() { # url dest
  echo "[dicts] $2"
  curl -fL --retry 3 -o "$2.part" "$1"
  mv "$2.part" "$2"
}

# British English (for Vale spelling)
fetch "$BASE/en/en_GB.aff" "$DICTS/en_GB.aff"
fetch "$BASE/en/en_GB.dic" "$DICTS/en_GB.dic"

# Swiss German frami (reference / LibreOffice / LaTeX; not used by Vale)
fetch "$BASE/de/de_CH_frami.aff" "$DICTS/de_CH_frami.aff"
fetch "$BASE/de/de_CH_frami.dic" "$DICTS/de_CH_frami.dic"

# Seed the House vocabulary (accepted / rejected words) if absent.
[ -f "$VOCAB/accept.txt" ] || cat > "$VOCAB/accept.txt" <<'EOF'
# One accepted term per line (case-insensitive). Add product names,
# Helvetisms, jargon that Vale's en_GB speller should not flag.
holy-grail
homelab
LanguageTool
EOF
[ -f "$VOCAB/reject.txt" ] || printf '# One rejected term per line.\n' > "$VOCAB/reject.txt"

echo "[dicts] done:"
ls -la "$DICTS"
echo "[dicts] verify Vale sees them:  cd $SCRIPT_DIR && vale ls-config | grep -i dict || true"
