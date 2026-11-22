#!/usr/bin/env bash
# Format check for the notes pages that agents keep writing to: the batch backlog and the reminders.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: check-format.sh [FILE...]
Checks batch-backlog.md, reminders.md and batch reports (reports/<date>.md); default: the first two under NOTES_DIR/docs/claude from .env. Other files are skipped.
Run by build.sh and by the notes repo's pre-commit hook. Exit 1 with one line per problem.

Backlog (claude-config batch-homelab.md): "## Standing run rules", then one "## ✅|❓|⏸️ Title (repo)" per open item in execution order,
an intro line, a blank line, then the "- " list. Done items are deleted, never struck through or numbered.
Reports: the title (first line) names the file's date. All checked pages: a blank line before every list; backlog and reminders: no line longer than 400 characters; reminders: every table row has the header's cells.
EOF
}

case "${1:-}" in -h|--help) usage; exit 0 ;; esac
if [ $# = 0 ]; then
  notes=$(sed -n 's/^NOTES_DIR=//p' "$(dirname "$0")/.env")
  set -- "$notes/docs/claude/batch-backlog.md" "$notes/docs/claude/reminders.md"
fi

status=0
for f in "$@"; do
  case "$f" in */batch-backlog.md) kind=backlog ;; */reminders.md) kind=reminders ;; */reports/20[0-9][0-9]-[0-9][0-9]-[0-9][0-9].md) kind=report ;; *) continue ;; esac
  awk -v kind="$kind" -v name="$(basename "$f")" -v date="$(basename "$f" .md)" '
    function bad(msg) { printf "%s:%d: %s\n", name, NR, msg; errors++ }
    function cells(s) { gsub(/\\\|/, "", s); return gsub(/\|/, "|", s) - 1 }
    kind != "report" && length($0) > 400 { bad("line longer than 400 characters → split it into a short intro and a \"- \" list") }
    /^- / && prev != "" && prev !~ /^ *- / && prev !~ /^  / { bad("a list needs a blank line before it (else it renders as one paragraph)") }
    kind == "backlog" && (/^[0-9]+\. / || /~~/) { bad("open items are \"## ✅ Title (repo)\" headings, not numbered; done items are deleted") }
    kind == "backlog" && /^## / && $0 != "## Standing run rules" {
      if ($0 !~ /^## (✅|❓|⏸️) .+ \([^()]+\)$/) bad("item heading must be \"## ✅|❓|⏸️ Title (repo)\"")
      item = NR
    }
    kind == "backlog" && item && NR == item + 2 && ($0 == "" || /^- /) { bad("an item starts with one intro line after its heading") }
    kind == "report" && NR == 1 && (!/^# / || index($0, date) == 0) { bad("the title (first line) must be \"# … " date "\"") }
    kind == "reminders" && /^\|/ { n = cells($0); if (!want) want = n; else if (n != want) bad("table row has " n " cells, the header has " want) }
    kind == "reminders" && !/^\|/ { want = 0 }
    { prev = $0 }
    END { exit errors > 0 }
  ' "$f" || status=1
done
[ "$status" = 0 ] || echo "fix the lines above and save; the site rebuilds by itself (log: journalctl -u notes-build)" >&2
exit "$status"
