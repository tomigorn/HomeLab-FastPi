#!/usr/bin/env bash
# Every installer that creates the shared node-exporter textfile dir must keep its contract (docs/container-hardening.md): pi:65046, mode 2775. Usage: scripts/test_textfile_dir.sh
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }
want='install -d -o pi -g 65046 -m 2775 /var/lib/node-exporter/textfile'
mapfile -t hits < <(grep -rn --include='*.sh' -E 'install +-d .*/var/lib/node-exporter/textfile( |$)' "$REPO/Docker" "$REPO/Server" 2>/dev/null)
(( ${#hits[@]} >= 4 )) && ok "found ${#hits[@]} installers" || bad "installers found" "${#hits[@]}"
for h in "${hits[@]}"; do
  f=${h%%:*}; f=${f#"$REPO"/}
  [[ $h == *"$want"* ]] && ok "$f keeps pi:65046 2775" || bad "$f" "${h#*:*:}"
done
echo "textfile-dir: $PASS passed, $FAIL failed"; (( FAIL == 0 ))
