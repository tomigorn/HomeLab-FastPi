#!/usr/bin/env bash
# One place that decides how a script's message reaches the owner: action = Telegram now (oob-alert.sh), digest = a note in the 19:00 daily digest (node-exporter textfile, kept 48 h).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: notify.sh action <html message>       Telegram now, through oob-alert.sh (the owner must do something)
       notify.sh digest <source> <text>      no message: listed under "Notes from scripts" in the 19:00 daily digest
       notify.sh -h | --help
source: lowercase letters, digits, dashes (the script's name). text: plain text, at most 300 characters, newlines become spaces.
Next: curl -s localhost:9090/api/v1/query --data-urlencode 'query=homelab_digest_note_timestamp_seconds' to see the kept notes.
EOF
}

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
prom=${NOTIFY_PROM:-/var/lib/node-exporter/textfile/digest_notes.prom}
metric=homelab_digest_note_timestamp_seconds

esc() { local s=${1//\\/\\\\}; s=${s//\"/\\\"}; s=${s//$'\n'/ }; printf '%s' "${s//$'\r'/}"; }

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  action)
    [[ -n ${2:-} ]] || { usage >&2; exit 2; }
    exec "${NOTIFY_OOB:-$here/oob-alert.sh}" "$2"
    ;;
  digest)
    src=${2:-}; text=${3:-}
    [[ $src =~ ^[a-z0-9-]{1,40}$ && -n $text ]] || { echo "notify: digest needs <source> (a-z, 0-9, -) and <text>; try: notify.sh --help" >&2; exit 2; }
    text=${text//$'\n'/ }; text=$(esc "${text:0:300}")
    now=${NOTIFY_NOW:-$(date +%s)}
    line="$metric{source=\"$src\",text=\"$text\"}"
    exec 9>>"$prom.lock"
    flock 9
    tmp=$(mktemp "$prom.XXXXXX")
    trap 'rm -f "$tmp"' EXIT
    {
      echo "# HELP $metric Time a script left a note for the daily digest (Docker/_global/scripts/notify.sh)."
      echo "# TYPE $metric gauge"
      [[ -f $prom ]] && awk -v keep=$((now - 172800)) -v same="$line" '/^#/ { next } { v = $NF; k = substr($0, 1, length($0) - length(v) - 1); if (v + 0 >= keep && k != same) print }' "$prom"
      echo "$line $now"
    } > "$tmp"
    chmod 0644 "$tmp"
    mv "$tmp" "$prom"
    echo "notify: digest note from $src kept for the 19:00 digest ($prom)"
    ;;
  *) usage >&2; exit 2 ;;
esac
