# antivirus customizations (Docker/CUSTOMIZATIONS.md "antivirus").
AVD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../antivirus" && pwd)
if want clamav; then
  check av.scripts-in-image '^same same same$' "$(for f in scan.sh hostscan.sh entrypoint.sh; do [[ $(docker exec clamav sha256sum /$f 2>/dev/null | cut -d' ' -f1) == $(sha256sum < "$AVD/clamav/$f" | cut -d' ' -f1) ]] && echo same || echo "$f differs"; done | xargs)"
  check av.freshclam-conf '^same$' "$([[ $(docker exec clamav sha256sum /etc/clamav/freshclam.conf 2>/dev/null | cut -d' ' -f1) == $(sha256sum < "$AVD/clamav/freshclam.conf" | cut -d' ' -f1) ]] && echo same || echo differs)"
  check av.freshclam-running '^[1-9]' "$(docker exec clamav pgrep freshclam | wc -l)"
  check av.nightly-scan '^yes$' "$(s=$(sed -n 's/^clamav_last_run_timestamp_seconds{.*mode="new"} //p' /var/lib/node-exporter/textfile/clamav.prom 2>/dev/null); s=${s%.*}; (( $(date +%s) - ${s:-0} < 172800 )) && echo yes || echo "no (${s:-none})")"
fi
check av.timers '^active active same same$' "$(echo "$(systemctl is-active clamav-scan.timer clamav-hostscan.timer | xargs) $(for u in clamav-scan clamav-hostscan; do cmp -s /etc/systemd/system/$u.timer "$AVD/systemd/$u.timer" && echo same || echo differs; done | xargs)")"
check av.hostscan-no-network '^none$' "$(cd "$AVD" && docker compose --profile hostscan config --format json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["clamav-hostscan"].get("network_mode"))')"
check av.services '^same same$' "$(for u in clamav-scan clamav-hostscan; do cmp -s /etc/systemd/system/$u.service "$AVD/systemd/$u.service" && echo same || echo differs; done | xargs)"
check av.hostscan-resume '^1 2$' "$(cd "$AVD" && docker compose --profile hostscan config --format json 2>/dev/null | python3 -c 'import json,sys; s=json.load(sys.stdin)["services"]["clamav-hostscan"]; e=s["environment"]; print(e.get("SCAN_RESUME"), s.get("cpu_shares"))')"
