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
  "cat /home/buntu/.local/state/indexer-bar/storage.prom") cat "$FAKE_ST" ;;
  "cat /var/lib/beefy-mover/mover.prom") cat "$FAKE_MV" ;;
  *) exit 1 ;;
esac
STUB
chmod +x "$T/ssh"
printf '%s\n' '# TYPE beefy_watchdog_digest_updated_timestamp_seconds gauge' 'beefy_watchdog_digest_updated_timestamp_seconds 100' > "$T/wd"
printf '%s\n' 'beefy_storage_avail_bytes{branch="ssd"} 5' 'beefy_storage_updated_timestamp_seconds 200' > "$T/st"
printf '%s\n' 'beefy_mover_last_run_success 1' 'beefy_mover_last_run_timestamp_seconds 300' > "$T/mv"
export PATH="$T:$PATH" DEST="$T/idle.prom" WD_DEST="$T/wd.prom" FAKE_WD="$T/wd" ST_DEST="$T/st.prom" MV_DEST="$T/mv.prom" FAKE_ST="$T/st" FAKE_MV="$T/mv"
S="$HERE/beefy-idle-pull.sh"

"$S"
grep -q beefy_idle_busy "$T/idle.prom" && ok "idle metrics copied" || bad "idle metrics copied"
grep -q 'beefy_watchdog_digest_updated_timestamp_seconds 100' "$T/wd.prom" && ok "watchdog digest copied" || bad "watchdog digest copied"
[[ $(stat -c %a "$T/wd.prom") == 644 ]] && ok "watchdog file 0644" || bad "watchdog file 0644"
grep -q 'beefy_storage_updated_timestamp_seconds 200' "$T/st.prom" && ok "storage metrics copied" || bad "storage metrics copied"
grep -q 'beefy_mover_last_run_timestamp_seconds 300' "$T/mv.prom" && ok "mover metrics copied" || bad "mover metrics copied"
[[ $(stat -c %a "$T/st.prom") == 644 && $(stat -c %a "$T/mv.prom") == 644 ]] && ok "storage and mover files 0644" || bad "storage and mover files 0644"

FAKE_DOWN=1 "$S"
[[ ! -e $T/idle.prom ]] && ok "idle metrics removed while beefy is down" || bad "idle metrics removed while beefy is down"
grep -q 'timestamp_seconds 100' "$T/wd.prom" && ok "watchdog digest kept while beefy is down" || bad "watchdog digest kept while beefy is down"

grep -q 'timestamp_seconds 200' "$T/st.prom" && grep -q 'timestamp_seconds 300' "$T/mv.prom" && ok "storage and mover kept while beefy is down" || bad "storage and mover kept while beefy is down"

echo 'garbage' > "$T/st"; echo 'garbage' > "$T/mv"; echo 'garbage' > "$T/wd"; "$S"
grep -q 'timestamp_seconds 200' "$T/st.prom" && grep -q 'timestamp_seconds 300' "$T/mv.prom" && ok "invalid storage and mover files do not replace the copies" || bad "invalid storage and mover files do not replace the copies"
grep -q 'timestamp_seconds 100' "$T/wd.prom" && ok "invalid watchdog file does not replace the copy" || bad "invalid watchdog file does not replace the copy"
ls "$T" | grep -qE '(wd|st|mv).prom\.' && bad "no temp file left" || ok "no temp file left"

echo "$PASS passed, $FAIL failed"
[[ $FAIL == 0 ]]
