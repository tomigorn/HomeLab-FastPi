#!/usr/bin/env bash
# Runs beefy-idle-pull.sh against a fake ssh. Usage: ./test_beefy_idle_pull.sh
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }

cat > "$T/ssh" <<'STUB'
#!/usr/bin/env bash
[[ -n ${FAKE_DOWN:-} ]] && exit 255
case "${*: -1}" in
  "cat /run/beefy-idle.prom") echo 'beefy_idle_busy{reason="ssh"} 1' ;;
  "cat /home/buntu/.local/state/movie-downloads/watchdog-digest.prom") cat "$FAKE_WD" ;;
  *) exit 1 ;;
esac
STUB
chmod +x "$T/ssh"
printf '%s\n' '# TYPE beefy_watchdog_digest_updated_timestamp_seconds gauge' 'beefy_watchdog_digest_updated_timestamp_seconds 100' > "$T/wd"
export PATH="$T:$PATH" DEST="$T/idle.prom" WD_DEST="$T/wd.prom" FAKE_WD="$T/wd"
S="$HERE/beefy-idle-pull.sh"

"$S"
grep -q beefy_idle_busy "$T/idle.prom" && ok "idle metrics copied" || bad "idle metrics copied"
grep -q 'beefy_watchdog_digest_updated_timestamp_seconds 100' "$T/wd.prom" && ok "watchdog digest copied" || bad "watchdog digest copied"
[[ $(stat -c %a "$T/wd.prom") == 644 ]] && ok "watchdog file 0644" || bad "watchdog file 0644"

FAKE_DOWN=1 "$S"
[[ ! -e $T/idle.prom ]] && ok "idle metrics removed while beefy is down" || bad "idle metrics removed while beefy is down"
grep -q 'timestamp_seconds 100' "$T/wd.prom" && ok "watchdog digest kept while beefy is down" || bad "watchdog digest kept while beefy is down"

echo 'garbage' > "$T/wd"; "$S"
grep -q 'timestamp_seconds 100' "$T/wd.prom" && ok "invalid watchdog file does not replace the copy" || bad "invalid watchdog file does not replace the copy"
ls "$T" | grep -q 'wd.prom.' && bad "no temp file left" || ok "no temp file left"

echo "$PASS passed, $FAIL failed"
[[ $FAIL == 0 ]]
