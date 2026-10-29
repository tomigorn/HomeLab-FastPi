#!/usr/bin/env bash
# A unit that runs as root must not execute code pi can write (/home): root copies live in /usr/local/libexec/fastpi (install-root-scripts.sh). Usage: scripts/test_root_units.sh
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
INSTALLER="$REPO/Docker/_global/install-root-scripts.sh"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }
while IFS= read -r u; do
  rel=${u#"$REPO"/}; usr=$(sed -n 's/^User=//p' "$u" | tail -1)
  if [[ -z $usr || $usr == root ]]; then lines=$(grep -E '^Exec[A-Za-z]*=' "$u")
  else lines=$(grep -E '^Exec[A-Za-z]*=[-@:]*[+!]' "$u"); fi
  if grep -q '/home/' <<<"$lines"; then bad "$rel runs pi-writable code as root" "$(grep -m1 '/home/' <<<"$lines")"; continue; fi
  for p in $(grep -o '/usr/local/libexec/fastpi/[^ ]*' <<<"$lines" | sort -u); do
    grep -qF -- "${p#/usr/local/libexec/fastpi/}" "$INSTALLER" 2>/dev/null && ok "$rel: ${p##*/} installed by install-root-scripts.sh" || bad "$rel: $p" "not in install-root-scripts.sh"
  done
done < <(find "$REPO/Docker" "$REPO/Server" -name '*.service' -not -path '*/node_modules/*' 2>/dev/null | sort)
ok "scanned units"
echo "root-units: $PASS passed, $FAIL failed"; (( FAIL == 0 ))
