#!/usr/bin/env bash
# =========================================================
# lt-entrypoint.sh
# =========================================================
# Wraps the LanguageTool image's start.sh. It runs INSIDE the container
# (as user `languagetool`, which owns /LanguageTool/) and mutates LT's
# own on-disk resources before handing off. All effects are scoped to
# the container's ephemeral filesystem; the host's read-only shared/
# tree is never written to.
#
# Three jobs, in order:
#
#  1) SPELLING — append shared/spelling/<region>/spelling.txt to LT's
#     variant-specific custom-spelling file, so Helvetisms / house terms
#     are accepted as correctly spelled (and their compounds too — LT
#     accepts compounds built from any word in spelling*.txt).
#
#     Targets are the LT-intended, update-safe extension files, chosen
#     per region (the file names are NOT uniform across languages):
#         de_CH -> resource/de/hunspell/spelling-de-CH.txt
#         en_GB -> resource/en/hunspell/spelling_en-GB.txt
#     Falling back to <lang>/hunspell/spelling_custom.txt if the exact
#     variant file is absent in a future image.
#
#  2) RULES — merge our custom grammar fragments into LT's built-in
#     grammar.xml for the matching language OR variant:
#         shared/rules/<lang>/grammar.xml           -> rules/<lang>/grammar.xml
#         shared/rules/<lang>/<variant>/grammar.xml -> rules/<lang>/<variant>/grammar.xml
#     Variant files (e.g. de/de-CH) fire ONLY for that variant, so Swiss
#     rules never leak into de-DE. Inner <category>/<rule>/<rulegroup>
#     elements are inserted before the built-in file's final </rules>;
#     built-in rules above are preserved.
#
#  3) DISABLED RULES — compile shared/config/disabled-rules.txt (a
#     commented, one-ID-per-line file) into a single comma-separated
#     value and export it as `langtool_disabledRuleIds`. The image's
#     start.sh turns every `langtool_*` env var into a line in
#     config.properties, and LT reads `disabledRuleIds` from there to
#     switch those rules off GLOBALLY, for every request. This is the
#     permanent, traceable kill-switch: one rule ID per line, commit,
#     restart.
#
# Then: exec bash start.sh (the image's own launcher).
# =========================================================
set -euo pipefail

SHARED="${LT_SHARED_DIR:-/shared}"
LT_HOME="/LanguageTool"
LOG_PREFIX="[lt-entrypoint]"

log() { echo "${LOG_PREFIX} $*"; }

# ---------------------------------------------------------
# Region -> exact LT custom-spelling target file.
# The base language is derived from the prefix (de_CH -> de).
# The variant file name differs per language, so map explicitly;
# fall back to spelling_custom.txt (always present) if missing.
# ---------------------------------------------------------
spelling_target() {
  # $1 = region (e.g. de_CH); echoes an absolute path or empty.
  local region="$1"
  local base="${region%%_*}"
  local dir="$LT_HOME/org/languagetool/resource/$base/hunspell"
  local variant_file
  case "$region" in
    de_CH) variant_file="$dir/spelling-de-CH.txt" ;;   # note: dashes
    de_AT) variant_file="$dir/spelling-de-AT.txt" ;;
    en_GB) variant_file="$dir/spelling_en-GB.txt" ;;    # note: underscore + dash
    en_US) variant_file="$dir/spelling_en-US.txt" ;;
    en_AU) variant_file="$dir/spelling_en-AU.txt" ;;
    en_CA) variant_file="$dir/spelling_en-CA.txt" ;;
    *)     variant_file="" ;;
  esac
  if [ -n "$variant_file" ] && [ -f "$variant_file" ]; then
    echo "$variant_file"; return
  fi
  # Fallback: LT's generic per-language custom file.
  if [ -f "$dir/spelling_custom.txt" ]; then
    echo "$dir/spelling_custom.txt"; return
  fi
  echo ""
}

# Strip our previously-appended marker block from a file (idempotency).
strip_block() {
  # $1 = file, $2 = begin marker, $3 = end marker
  local f="$1" b="$2" e="$3" tmp
  if grep -qF "$b" "$f"; then
    tmp=$(mktemp)
    awk -v b="$b" -v e="$e" '
      index($0, b) { skip=1; next }
      index($0, e) { skip=0; next }
      !skip        { print }
    ' "$f" > "$tmp"
    cp "$tmp" "$f"
    rm -f "$tmp"
  fi
}

# ---------------------------------------------------------
# 1) Spelling additions
# ---------------------------------------------------------
if [ -d "$SHARED/spelling" ]; then
  for region_dir in "$SHARED"/spelling/*/; do
    [ -d "$region_dir" ] || continue
    region=$(basename "$region_dir")            # e.g. de_CH, en_GB
    src="$region_dir/spelling.txt"
    [ -f "$src" ] || continue

    dst=$(spelling_target "$region")
    if [ -z "$dst" ]; then
      log "WARN: no spelling target found for region $region — skipping"
      continue
    fi

    marker_begin="# === BEGIN appended from shared/spelling/$region/spelling.txt ==="
    marker_end="# === END appended from shared/spelling/$region/spelling.txt ==="

    strip_block "$dst" "$marker_begin" "$marker_end"

    {
      echo ""
      echo "$marker_begin"
      grep -vE '^[[:space:]]*(#|$)' "$src" || true
      echo "$marker_end"
    } >> "$dst"

    count=$(grep -cvE '^[[:space:]]*(#|$)' "$src" || true)
    log "spelling: appended ${count} word(s) from ${region} -> ${dst}"
  done
fi

# ---------------------------------------------------------
# 2) Custom grammar rules (language- and variant-level)
# ---------------------------------------------------------
merge_grammar() {
  # $1 = source fragment path, $2 = destination built-in grammar.xml
  local src="$1" dst="$2"
  [ -f "$src" ] || return 0
  if [ ! -f "$dst" ]; then
    log "WARN: target $dst does not exist — skipping $src"
    return 0
  fi

  local rel="${src#$SHARED/}"
  local marker_begin="<!-- === BEGIN merged from shared/$rel === -->"
  local marker_end="<!-- === END merged from shared/$rel === -->"

  strip_block "$dst" "$marker_begin" "$marker_end"

  # Extract the inner children of the outer <rules lang=...> wrapper.
  # Robust to a multi-LINE opening tag (attributes wrapped across lines):
  #   state 0 = before <rules>; 1 = inside the opening tag, seeking its
  #   closing '>'; 2 = inside the body, emitting until the first </rules>.
  # Requires lang= in the opening tag so a stray "<rules>" in a comment
  # is not matched.
  # The opening <rules …> tag and the closing </rules> each begin their
  # own line (after optional indentation); prose that merely mentions
  # "<rules lang=…>" inside a header comment does NOT start the line, so
  # anchoring to line-start avoids matching commentary.
  local inner
  inner=$(awk '
    BEGIN { state = 0 }
    state == 0 {
      t = $0; sub(/^[ \t]+/, "", t)
      if (t ~ /^<rules[ \t]/) {
        gt = index(t, ">")
        if (gt > 0) { line = substr(t, gt + 1); state = 2; if (length(line) > 0) print line }
        else        { state = 1 }
      }
      next
    }
    state == 1 {
      gt = index($0, ">")
      if (gt > 0) { line = substr($0, gt + 1); state = 2; if (length(line) > 0) print line }
      next
    }
    state == 2 {
      t = $0; sub(/^[ \t]+/, "", t)
      if (t ~ /^<\/rules>/) { state = 3; next }
      print
    }
  ' "$src")

  if [ -z "$inner" ]; then
    log "WARN: no <rules>…</rules> content extracted from $src — skipping"
    return 0
  fi

  # Insert before the LAST </rules> of the destination.
  # IMPORTANT: do NOT pass $inner through `awk -v` — awk performs escape
  # processing on -v values, so backslash sequences in the rule content
  # (e.g. the \1 \2 back-references in <regexp> suggestions) would be
  # mangled into control characters. Splice with head/cat/tail instead,
  # which is byte-exact, and write $inner via a temp file.
  local last tmp inner_tmp
  last=$(grep -n '</rules>' "$dst" | tail -1 | cut -d: -f1)
  if [ -z "$last" ]; then
    log "WARN: no </rules> found in $dst — skipping"
    return 0
  fi
  inner_tmp=$(mktemp)
  printf '%s\n' "$inner" > "$inner_tmp"   # %s does not escape-process the arg
  tmp=$(mktemp)
  {
    head -n "$((last - 1))" "$dst"
    echo "$marker_begin"
    cat "$inner_tmp"
    echo "$marker_end"
    tail -n "+$last" "$dst"
  } > "$tmp"
  cp "$tmp" "$dst"
  rm -f "$tmp" "$inner_tmp"

  log "rules: merged shared/$rel -> ${dst}"
}

if [ -d "$SHARED/rules" ]; then
  for lang_dir in "$SHARED"/rules/*/; do
    [ -d "$lang_dir" ] || continue
    lang=$(basename "$lang_dir")                # e.g. de, en

    # 2a) language-level fragment: shared/rules/<lang>/grammar.xml
    merge_grammar "$lang_dir/grammar.xml" \
      "$LT_HOME/org/languagetool/rules/$lang/grammar.xml"

    # 2b) variant-level fragments: shared/rules/<lang>/<variant>/grammar.xml
    for variant_dir in "$lang_dir"*/; do
      [ -d "$variant_dir" ] || continue
      variant=$(basename "$variant_dir")        # e.g. de-CH, en-GB
      merge_grammar "$variant_dir/grammar.xml" \
        "$LT_HOME/org/languagetool/rules/$lang/$variant/grammar.xml"
    done
  done
fi

# ---------------------------------------------------------
# 3) Global disabled rules -> langtool_disabledRuleIds
# ---------------------------------------------------------
DISABLED_FILE="$SHARED/config/disabled-rules.txt"
if [ -f "$DISABLED_FILE" ]; then
  # One ID per line; strip comments/blanks; join with commas.
  ids=$(grep -vE '^[[:space:]]*(#|$)' "$DISABLED_FILE" \
        | awk '{$1=$1; print}' \
        | paste -sd, - || true)
  if [ -n "$ids" ]; then
    # Merge with any disabledRuleIds already set in the environment.
    if [ -n "${langtool_disabledRuleIds:-}" ]; then
      export langtool_disabledRuleIds="${langtool_disabledRuleIds},${ids}"
    else
      export langtool_disabledRuleIds="$ids"
    fi
    n=$(echo "$ids" | tr ',' '\n' | grep -c .)
    log "disabled: ${n} rule ID(s) -> langtool_disabledRuleIds"
  else
    log "disabled: none active in $DISABLED_FILE"
  fi
fi

# ---------------------------------------------------------
# Hand off to LanguageTool's own start.sh
# ---------------------------------------------------------
log "handing off to bash start.sh"
exec bash "$LT_HOME/start.sh"
