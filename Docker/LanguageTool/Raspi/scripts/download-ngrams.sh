#!/usr/bin/env bash
# =========================================================
# download-ngrams.sh — fetch en + de n-gram datasets
# =========================================================
# Datasets come from https://languagetool.org/download/ngram-data/
# Both languages: ~25 GB unpacked on disk. Re-downloadable; not backed up.
# =========================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NGRAMS_DIR="$SCRIPT_DIR/../ngrams"
NGRAMS_DIR="$(cd "$NGRAMS_DIR" && pwd)"

URLS=(
  "en|https://languagetool.org/download/ngram-data/ngrams-en-20150817.zip"
  "de|https://languagetool.org/download/ngram-data/ngrams-de-20150819.zip"
)

mkdir -p "$NGRAMS_DIR"
cd "$NGRAMS_DIR"

for entry in "${URLS[@]}"; do
  lang="${entry%%|*}"
  url="${entry##*|}"
  zip="$(basename "$url")"

  if [ -d "$lang/3grams" ]; then
    echo "[ngrams] $lang already present at $NGRAMS_DIR/$lang — skipping"
    continue
  fi

  echo "[ngrams] downloading $url"
  if [ ! -f "$zip" ]; then
    curl -L --fail -o "$zip.part" "$url"
    mv "$zip.part" "$zip"
  fi

  echo "[ngrams] unpacking $zip"
  unzip -q "$zip"

  # Some archives extract into ngrams-<lang>-<date>/<lang>/, others
  # directly into <lang>/. Normalise.
  if [ ! -d "$lang" ]; then
    nested=$(find . -maxdepth 2 -type d -name "$lang" | head -n 1)
    if [ -n "$nested" ] && [ "$nested" != "./$lang" ]; then
      mv "$nested" "./$lang"
      # Drop empty wrapper dir
      find . -maxdepth 1 -type d -name "ngrams-${lang}-*" -empty -delete 2>/dev/null || true
    fi
  fi

  echo "[ngrams] verifying structure of $lang/"
  for sub in 1grams 2grams 3grams; do
    if [ ! -d "$lang/$sub" ]; then
      echo "  ERROR: missing $lang/$sub" >&2
      exit 1
    fi
    files=$(find "$lang/$sub" -maxdepth 1 -type f | wc -l)
    echo "  $lang/$sub: $files file(s)"
  done

  rm -f "$zip"
done

echo "[ngrams] done. Total size: $(du -sh "$NGRAMS_DIR" | cut -f1)"
