#!/usr/bin/env bash
# Tests for ../check-format.sh: good pages pass, each broken layout fails with its line.
set -uo pipefail
CHECK="$(dirname "$0")/../check-format.sh"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
fails=0

expect() {  # expect <0|1> <name> <file> [grep pattern in output]
  out=$("$CHECK" "$3" 2>&1); code=$?
  if [ "$code" != "$1" ] || { [ -n "${4:-}" ] && ! grep -q -- "$4" <<<"$out"; }; then
    echo "FAIL $2 (exit $code)"; echo "$out" | sed 's/^/    /'; fails=$((fails + 1))
  else
    echo "ok   $2"
  fi
}

mkdir -p "$tmp/docs"
backlog="$tmp/docs/batch-backlog.md"
good_backlog() {
  cat > "$backlog" <<'EOF'
# Batch backlog

Queue for the next batch.

## Standing run rules

- Stop dispatching at 80 % usage.

## ✅ Phone versions: transcode fallback (beefy)

Own QSV transcode when no fitting release is left · Opus

- Spec: `/home/pi/reports/specs/x.md`
- Band "Converting x %"

## ❓ Region collections (beefy)

One collection per region · Sonnet

- ❓ by country or language?

## ⏸️ HDD auto-delete (beefy)

Later, owner 2026-11-19 · Opus

- Keep forever flag
EOF
}

good_backlog
expect 0 "good backlog passes" "$backlog"

good_backlog; sed -i 's/^## ✅ Phone versions: transcode fallback (beefy)/## Phone versions: transcode fallback (beefy)/' "$backlog"
expect 1 "item heading without status" "$backlog" "batch-backlog.md:9"

good_backlog; sed -i 's/^## ❓ Region collections (beefy)/## ❓ Region collections/' "$backlog"
expect 1 "item heading without repo" "$backlog" "(repo)"

good_backlog; sed -i '/^Own QSV transcode/{n;d}' "$backlog"
expect 1 "no blank line before the list" "$backlog" "blank line"

good_backlog; sed -i 's/^Own QSV transcode.*/- Own QSV transcode/' "$backlog"
expect 1 "no intro line" "$backlog" "intro line"

good_backlog; echo "1. ~~Old item~~ DONE" >> "$backlog"
expect 1 "numbered or struck-through item" "$backlog" "not numbered"

good_backlog; printf -- '- %0400d\n' 0 >> "$backlog"
expect 1 "overlong line" "$backlog" "longer than"

reminders="$tmp/docs/reminders.md"
cat > "$reminders" <<'EOF'
# Open decisions and reminders

| Due | What | Decision / action | How you get reminded |
|---|---|---|---|
| 2099-01-01 | Something | decide | Claude reminds you |
EOF
expect 0 "good reminders pass" "$reminders"

echo "| 2099-01-02 | Broken row | missing cells |" >> "$reminders"
expect 1 "reminder row with the wrong cell count" "$reminders" "reminders.md:6"

echo "intro"$'\n'"- list right after text" > "$tmp/docs/reminders.md"
expect 1 "reminders: list needs a blank line" "$reminders" "blank line"

mkdir -p "$tmp/docs/claude/reports"
report="$tmp/docs/claude/reports/2026-11-22.md"
good_report() {
  cat > "$report" <<'EOF'
# 🌙🛠️📋 Batch report — 2026-11-22

## Daytime run

**6 done · 10:12→12:45 (2h 33m)**

- ✅ **Item** — 10:15→10:25 · Sonnet
  What happened, a line that may be long.
EOF
}
good_report
expect 0 "good report passes" "$report"

good_report; printf -- '- %0450d\n' 0 >> "$report"
expect 0 "report lines may be long" "$report"

good_report; sed -i '1s/2026-11-22/2026-11-21/' "$report"
expect 1 "report title without its date" "$report" "2026-11-22.md:1"

good_report; sed -i '/^\*\*6 done/{n;d}' "$report"
expect 1 "report: list needs a blank line" "$report" "blank line"

expect 0 "other pages are not checked" /dev/null

[ "$fails" = 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
