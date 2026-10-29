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
  "head -c 262145 /run/beefy-idle.prom") cat "$FAKE_ID" ;;
  "head -c 262145 /home/buntu/.local/state/movie-downloads/watchdog-digest.prom") cat "$FAKE_WD" ;;
  "head -c 262145 /home/buntu/.local/state/indexer-bar/storage.prom") cat "$FAKE_ST" ;;
  "head -c 262145 /var/lib/beefy-mover/mover.prom") cat "$FAKE_MV" ;;
  "head -c 262145 /var/lib/smart-exporter/smart_beefy.prom") cat "$FAKE_SM" ;;
  "head -c 262145 /home/buntu/.local/state/movie-downloads/media-metrics.prom") cat "$FAKE_MM" ;;
  "head -c 262145 /home/buntu/.local/state/jellyfin-popular.prom") cat "$FAKE_JP" ;;
  *) exit 1 ;;
esac
STUB
chmod +x "$T/ssh"
printf '%s\n' '# TYPE beefy_idle_busy gauge' 'beefy_idle_busy{reason="ssh"} 1' 'beefy_boot_time_seconds 1700000000' > "$T/id"
printf '%s\n' '# TYPE beefy_watchdog_digest_updated_timestamp_seconds gauge' 'beefy_watchdog_digest_updated_timestamp_seconds 100' > "$T/wd"
printf '%s\n' 'beefy_storage_avail_bytes{branch="ssd"} 5' 'beefy_storage_updated_timestamp_seconds 200' > "$T/st"
printf '%s\n' 'beefy_mover_last_run_success 1' 'beefy_mover_last_run_timestamp_seconds 300' > "$T/mv"
printf '%s\n' 'smart_standby{host="beefy",disk="hdd-cold"} 1' 'smart_exporter_last_run_timestamp_seconds{host="beefy"} 400' > "$T/sm"
printf '%s\n' 'beefy_requests{state="total"} 4' 'indexer_used{host="beefy",indexer="Some \"Name\"",kind="searches"} 3' 'beefy_media_metrics_updated_timestamp_seconds 500' > "$T/mm"
printf '%s\n' 'jf_popular_last_run_timestamp_seconds 600' > "$T/jp"
export FAKE_ID="$T/id" SM_DEST="$T/sm.prom" MM_DEST="$T/mm.prom" JP_DEST="$T/jp.prom" FAKE_SM="$T/sm" FAKE_MM="$T/mm" FAKE_JP="$T/jp"
export PATH="$T:$PATH" DEST="$T/idle.prom" WD_DEST="$T/wd.prom" FAKE_WD="$T/wd" ST_DEST="$T/st.prom" MV_DEST="$T/mv.prom" FAKE_ST="$T/st" FAKE_MV="$T/mv"
S="$HERE/beefy-idle-pull.sh"

"$S"
grep -q beefy_idle_busy "$T/idle.prom" && ok "idle metrics copied" || bad "idle metrics copied"
grep -q 'beefy_watchdog_digest_updated_timestamp_seconds 100' "$T/wd.prom" && ok "watchdog digest copied" || bad "watchdog digest copied"
[[ $(stat -c %a "$T/wd.prom") == 644 ]] && ok "watchdog file 0644" || bad "watchdog file 0644"
grep -q 'beefy_storage_updated_timestamp_seconds 200' "$T/st.prom" && ok "storage metrics copied" || bad "storage metrics copied"
grep -q 'beefy_mover_last_run_timestamp_seconds 300' "$T/mv.prom" && ok "mover metrics copied" || bad "mover metrics copied"
[[ $(stat -c %a "$T/st.prom") == 644 && $(stat -c %a "$T/mv.prom") == 644 ]] && ok "storage and mover files 0644" || bad "storage and mover files 0644"

grep -q 'timestamp_seconds{host="beefy"} 400' "$T/sm.prom" && ok "smart metrics copied" || bad "smart metrics copied"
grep -q 'beefy_media_metrics_updated_timestamp_seconds 500' "$T/mm.prom" && ok "media metrics copied" || bad "media metrics copied"
grep -q 'jf_popular_last_run_timestamp_seconds 600' "$T/jp.prom" && ok "popular metrics copied" || bad "popular metrics copied"

FAKE_DOWN=1 "$S"
[[ ! -e $T/idle.prom ]] && ok "idle metrics removed while beefy is down" || bad "idle metrics removed while beefy is down"
grep -q 'timestamp_seconds 100' "$T/wd.prom" && ok "watchdog digest kept while beefy is down" || bad "watchdog digest kept while beefy is down"

grep -q 'timestamp_seconds 200' "$T/st.prom" && grep -q 'timestamp_seconds 300' "$T/mv.prom" && ok "storage and mover kept while beefy is down" || bad "storage and mover kept while beefy is down"

grep -q 400 "$T/sm.prom" && grep -q 500 "$T/mm.prom" && grep -q 600 "$T/jp.prom" && ok "smart, media and popular kept while beefy is down" || bad "smart, media and popular kept while beefy is down"

echo 'garbage' | tee "$T/sm" "$T/mm" "$T/jp" >/dev/null; echo 'garbage' > "$T/st"; echo 'garbage' > "$T/mv"; echo 'garbage' > "$T/wd"; "$S"
grep -q 'timestamp_seconds 200' "$T/st.prom" && grep -q 'timestamp_seconds 300' "$T/mv.prom" && ok "invalid storage and mover files do not replace the copies" || bad "invalid storage and mover files do not replace the copies"
grep -q 'timestamp_seconds 100' "$T/wd.prom" && ok "invalid watchdog file does not replace the copy" || bad "invalid watchdog file does not replace the copy"
grep -q 400 "$T/sm.prom" && grep -q 500 "$T/mm.prom" && grep -q 600 "$T/jp.prom" && ok "invalid smart, media and popular files do not replace the copies" || bad "invalid smart, media and popular files do not replace the copies"
ls "$T" | grep -qE '(wd|st|mv|sm|mm|jp).prom\.' && bad "no temp file left" || ok "no temp file left"

# Only each file's own metric names, host="beefy" on families fastpi also writes; anything else rejects the whole file.
good() { printf '%s\n' 'smart_standby{host="beefy",disk="hdd-cold"} 1' 'smart_exporter_last_run_timestamp_seconds{host="beefy"} 400' > "$T/sm"
         printf '%s\n' 'beefy_requests{state="total"} 4' 'indexer_used{host="beefy",indexer="Some \"Name\"",kind="searches"} 3' 'beefy_media_metrics_updated_timestamp_seconds 500' > "$T/mm"
         printf '%s\n' 'beefy_mover_last_run_success 1' 'beefy_mover_last_run_timestamp_seconds 300' > "$T/mv"
         printf '%s\n' 'jf_popular_last_run_timestamp_seconds 600' > "$T/jp"
         printf '%s\n' 'beefy_idle_busy{reason="ssh"} 1' > "$T/id"; }
reject() {  # reject <fixture> <dest> <name> <lines...>
    local fx=$1 dst=$2 name=$3; shift 3
    good; "$S"; local before; before=$(cat "$dst")
    { cat "$fx"; printf '%s\n' "$@"; } > "$fx.new"; mv "$fx.new" "$fx"; "$S"
    [[ -e $dst && $(cat "$dst") == "$before" ]] && ok "$name" || bad "$name" "$(cat "$dst" 2>/dev/null)"
}
reject "$T/sm" "$T/sm.prom" "smart: host=fastpi series rejected" 'smart_healthy{host="fastpi",disk="sd"} 1'
reject "$T/sm" "$T/sm.prom" "smart: series without host rejected" 'smart_healthy{disk="sd"} 1'
reject "$T/sm" "$T/sm.prom" "smart: duplicate host label rejected" 'smart_healthy{host="beefy",host="fastpi"} 1'
reject "$T/sm" "$T/sm.prom" "smart: TYPE for a shared family rejected" '# TYPE smart_healthy counter'
reject "$T/sm" "$T/sm.prom" "smart: foreign family rejected" 'security_rootkit_warnings{host="beefy",tool="rkhunter"} 0'
reject "$T/mm" "$T/mm.prom" "media: indexer of fastpi rejected" 'indexer_used{host="fastpi",indexer="X",kind="searches"} 1'
reject "$T/mm" "$T/mm.prom" "media: fastpi backup family rejected" 'beefy_backup_snapshots 30'
reject "$T/mv" "$T/mv.prom" "mover: security family rejected" 'security_rootkit_warnings{host="fastpi",tool="rkhunter"} 0'
reject "$T/mv" "$T/mv.prom" "mover: TYPE of a foreign family rejected" '# TYPE beefy_backup_snapshots gauge'
reject "$T/mv" "$T/mv.prom" "mover: host label other than beefy rejected" 'beefy_mover_moved_titles{host="fastpi"} 1'
reject "$T/jp" "$T/jp.prom" "popular: malformed sample rejected" 'jf_popular_items{list="a"} 1 2 3'
reject "$T/jp" "$T/jp.prom" "popular: unterminated label rejected" 'jf_popular_items{list="a} 1'
good; "$S"; head -c 300000 /dev/zero | tr '\0' '#' >> "$T/jp"; cp "$T/jp.prom" "$T/jp.before"; "$S"
cmp -s "$T/jp.prom" "$T/jp.before" && ok "oversized file rejected" || bad "oversized file rejected"
good; printf '%s\n' 'security_rootkit_warnings{host="fastpi",tool="rkhunter"} 0' >> "$T/id"; "$S"
[[ ! -e $T/idle.prom ]] && ok "idle file with foreign series removed" || bad "idle file with foreign series removed"
good; "$S"; grep -qF 'indexer="Some \"Name\""' "$T/mm.prom" && grep -q beefy_idle_busy "$T/idle.prom" && ok "valid files (escaped label value) copied after rejections" || bad "valid files (escaped label value) copied after rejections"

echo "$PASS passed, $FAIL failed"
[[ $FAIL == 0 ]]
