#!/usr/bin/env bash
# =========================================================
# test.sh — end-to-end verification of the LanguageTool setup
# =========================================================
# Asserts, against the RUNNING container, that:
#   * en-GB and de-CH are advertised
#   * every custom / curated rule that MUST fire, fires
#   * every spelling that MUST be accepted, is accepted
#   * disabled rules stay silent
#
# Exits non-zero on the first failed assertion.
#
# Targets the container directly (no host port on the Pi): it execs
# `curl` inside the languagetool container. Override with LT_EXEC=0 and
# LT_URL=... to hit a published port instead.
# =========================================================
set -uo pipefail

LT_EXEC="${LT_EXEC:-1}"
LT_URL="${LT_URL:-http://localhost:8010}"

if [ "$LT_EXEC" = "1" ] && command -v docker >/dev/null 2>&1 \
   && docker ps --format '{{.Names}}' | grep -q '^languagetool$'; then
  echo "[test] hitting LT via: docker exec languagetool curl …"
  _curl() { docker exec languagetool curl -sS --max-time 15 "$@"; }
else
  echo "[test] hitting LT at $LT_URL"
  _curl() { curl -sS --max-time 15 "$@"; }
fi

pass=0; fail=0
ok()   { echo "  ✔ $*"; pass=$((pass+1)); }
bad()  { echo "  x FAIL: $*" >&2; fail=$((fail+1)); }

# ids <lang> <level> <text>  ->  newline-separated rule IDs of all matches
ids() {
  _curl "$LT_URL/v2/check" \
    --data-urlencode "language=$1" \
    --data-urlencode "level=$2" \
    --data-urlencode "text=$3" \
  | python3 -c "import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    sys.exit('  (no JSON response — server error?)')
print('\n'.join(m['rule']['id'] for m in d['matches']))"
}

must_fire()      { # label lang level text ruleid
  local out; out="$(ids "$2" "$3" "$4")"
  if grep -qx "$5" <<<"$out"; then ok "$1 → $5 fired"
  else bad "$1 → expected $5, got: $(tr '\n' ' ' <<<"$out")"; fi
}
must_not_match() { # label lang level text ruleid-substring
  local out; out="$(ids "$2" "$3" "$4")"
  if grep -q "$5" <<<"$out"; then bad "$1 → $5 fired but should not (got: $(tr '\n' ' ' <<<"$out"))"
  else ok "$1 → $5 silent"; fi
}

echo
echo "[0] languages advertised"
langs="$(_curl "$LT_URL/v2/languages")"
grep -q '"longCode":"en-GB"' <<<"$langs" && ok "en-GB advertised" || bad "en-GB missing"
grep -q '"longCode":"de-CH"' <<<"$langs" && ok "de-CH advertised" || bad "de-CH missing"

echo
echo "[1] de-CH — rules that MUST fire"
must_fire "ß→ss"          de-CH picky "Es war ein großer Erfolg."                 SWISS_NO_ESZETT
must_fire "Helvetism Velo" de-CH picky "Ich fahre mit dem Fahrrad zur Bar."       HELVETISM_FAHRRAD
must_fire "Helvetism Rahm" de-CH picky "Ich nehme Sahne in den Kaffee."           HELVETISM_SAHNE
must_fire "Helvetism Tram" de-CH picky "Ich nehme die Strassenbahn."              HELVETISM_STRASSENBAHN
must_fire "thousands '"    de-CH picky "Die Stadt hat 1,000,000 Einwohner."       SWISS_THOUSANDS_APOSTROPHE
must_fire "CHF format"     de-CH picky "Der Preis beträgt CHF 1.500,00."          SWISS_CHF_FORMAT
must_fire "guillemet open" de-CH picky "Er sagte „Grüezi“."                       SWISS_GUILLEMET_OPEN
must_fire "guillemet close" de-CH picky "Er sagte „Grüezi“."                      SWISS_GUILLEMET_CLOSE

echo
echo "[2] de-CH — Helvetisms that MUST be accepted (no spelling error)"
must_not_match "Velo/Beiz/parkieren/grillieren" \
  de-CH picky "Ich gehe mit dem Velo zur Beiz, will dort parkieren und dann grillieren." GERMAN_SPELLER
must_not_match "Glace/Apéro/Gipfeli/Znüni" \
  de-CH picky "Zum Znüni gab es ein Gipfeli, danach ein Apéro und eine Glace." GERMAN_SPELLER

echo
echo "[3] en-GB — rules that MUST fire"
must_fire "-ise organise"  en-GB picky "We need to organize the files."           EN_GB_ISE_CONSISTENCY
must_fire "aeroplane"      en-GB picky "We boarded the airplane."                 EN_GB_SIMPLE_REPLACE_AIRPLANE

echo
echo "[4] en-GB — correct British spelling MUST be accepted (Oxford rules disabled)"
must_not_match "organise accepted"  en-GB picky "We organise and realise this."   OXFORD_SPELLING
must_not_match "colour accepted"    en-GB picky "The colour of the flavour."      MORFOLOGIK

echo
echo "[5] no AI / n-gram rules present"
must_not_match "no confusion/ngram" en-GB picky "I can't remember there name."    CONFUSION

echo
echo "========================================================="
echo "  PASS: $pass    FAIL: $fail"
echo "========================================================="
[ "$fail" -eq 0 ]
