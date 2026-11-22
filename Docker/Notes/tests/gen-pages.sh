#!/usr/bin/env bash
# Tests for ../gen-pages.sh: generated pages of the Claude section from a fixture notes dir and fixture repos.
set -uo pipefail
GEN="$(dirname "$0")/../gen-pages.sh"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
fails=0

check() {  # check <name> <file> <grep pattern> [absent]
  if [ "${4:-}" = absent ]; then grep -q -- "$3" "$2" 2>/dev/null && { echo "FAIL $1: found '$3' in $2"; fails=$((fails + 1)); return; }
  else grep -q -- "$3" "$2" 2>/dev/null || { echo "FAIL $1: no '$3' in $2"; sed 's/^/    /' "$2" 2>/dev/null; fails=$((fails + 1)); return; }; fi
  echo "ok   $1"
}

n="$tmp/notes"; c="$n/docs/claude"
mkdir -p "$c/batches" "$c/reports/2026-11-21-shots" "$tmp/repo-a/docs" "$tmp/repo-b/docs/working" "$tmp/repo-c"
git -C "$n" init -q
printf '# Batch 2026-11-21 — handoff\n' > "$c/batches/2026-11-21.md"
printf '# Batch 2026-11-22 — handoff\n' > "$c/batches/2026-11-22.md"
printf '# 🌙🛠️📋 Batch report — 2026-11-21\n\n**3 done · 03:00→04:00 (1h)**\n' > "$c/reports/2026-11-21.md"
printf '# Reports — 2026-10-23\n\n- [Old](archive/2026-10-23/old.md)\n' > "$c/reports/2026-10-23.md"
cat > "$c/reports/2026-11-22.md" <<'EOF'
# 🌙🛠️📋 Batch report — 2026-11-22

## Night run

**4 done · 02:26→07:50 (5h 24m)**

## ❓ Your decisions

- ❓ Keep the night slot?

## Daytime run

**6 done · 10:12→12:45 (2h 33m)**

### ❓ Your decisions

- ❓ Rename the row? ⭐ yes
- ❓ Wake beefy at 22:05?

### ✋ By hand

- ✋ Not a question
EOF
cat > "$c/reminders.md" <<'EOF'
# Open decisions and reminders

| Due | What | Decision / action | How you get reminded |
|---|---|---|---|
| 2026-11-27 | Eweka subscription | renew on Black Friday | Claude reminds you |

## Done

| Date | What |
|---|---|
| 2026-11-20 | Old thing |
EOF
cat > "$tmp/repo-a/docs/roadmap.md" <<'EOF'
# Roadmap

| Feature | Status |
|---|---|
| Thing ([spec](specs/thing.md)) | 🔨 working |
| External ([docs](https://example.com/x)) | 📋 todo |

## Open questions

- Which colour for the badge?

## By hand
EOF
printf '# Roadmap (b)\n\n## Open questions\n\n## Done\n' > "$tmp/repo-b/docs/working/roadmap.md"

ROADMAP_REPOS="alpha=$tmp/repo-a beta=$tmp/repo-b gamma=$tmp/repo-c" "$GEN" "$n" || { echo "FAIL gen-pages exit $?"; fails=$((fails + 1)); }

check "reports index lists newest first" "$c/reports/index.md" "2026-11-22"
[ "$(grep -o '20[0-9-]*\.md' "$c/reports/index.md" | head -1)" = 2026-11-22.md ] && echo "ok   reports index order" || { echo "FAIL reports index order"; fails=$((fails + 1)); }
check "reports index shows the runs' stats" "$c/reports/index.md" "6 done"
check "reports index lists a page without summary" "$c/reports/index.md" "(2026-10-23.md)"
check "reports index skips shots folders" "$c/reports/index.md" "shots" absent
check "handoff index" "$c/batches/index.md" "(2026-11-22.md)"
check "roadmap copied" "$c/roadmaps/alpha.md" "Thing"
check "roadmap relative link made plain" "$c/roadmaps/alpha.md" "](specs/thing.md)" absent
check "roadmap web link kept" "$c/roadmaps/alpha.md" "(https://example.com/x)"
check "roadmap names its source" "$c/roadmaps/alpha.md" "$tmp/repo-a/docs/roadmap.md"
check "light-repo roadmap copied" "$c/roadmaps/beta.md" "Roadmap (b)"
[ ! -e "$c/roadmaps/gamma.md" ] && echo "ok   repo without roadmap skipped" || { echo "FAIL gamma page exists"; fails=$((fails + 1)); }
check "roadmaps index" "$c/roadmaps/index.md" "(alpha.md)"
q="$c/open-questions.md"
check "open q: roadmap question" "$q" "Which colour for the badge?"
check "open q: roadmap source link" "$q" "(roadmaps/alpha.md)"
check "open q: latest report decisions, all runs" "$q" "Keep the night slot?"
check "open q: latest report second run" "$q" "Wake beefy at 22:05?"
check "open q: report source link" "$q" "(reports/2026-11-22.md)"
check "open q: not the by-hand list" "$q" "Not a question" absent
check "open q: older report left out" "$q" "2026-11-21.md" absent
check "open q: reminder decision" "$q" "renew on Black Friday"
check "open q: reminder done rows left out" "$q" "Old thing" absent

before=$(stat -c %Y "$q"); sleep 1
ROADMAP_REPOS="alpha=$tmp/repo-a beta=$tmp/repo-b" "$GEN" "$n"
[ "$(stat -c %Y "$q")" = "$before" ] && echo "ok   unchanged page not rewritten" || { echo "FAIL page rewritten without change"; fails=$((fails + 1)); }

[ "$fails" = 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
