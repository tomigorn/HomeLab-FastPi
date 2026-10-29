# Host-level customizations on fastpi (Docker/CUSTOMIZATIONS.md "Host"): security monitoring, auto-update, firewall persistence. No compose project, so only "all" runs it.
SMD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../Server/4-Security-Monitoring" && pwd)
check host.security-timers '^active( active){7}$' "$(systemctl is-active security-scan.timer security-image-scan.timer security-av.timer security-av-hits.timer security-audit.timer security-access.timer security-code-scan.timer security-dt.timer | xargs)"
check host.security-units-installed '^0$' "$(n=0; for f in "$SMD"/security-*.service "$SMD"/security-*.timer; do cmp -s "$f" "/etc/systemd/system/$(basename "$f")" || n=$((n+1)); done; echo $n)"
check host.security-scan-fresh '^none$' "$(curl -s -m 5 http://127.0.0.1:9093/api/v2/alerts | python3 -c 'import json,sys; a=sorted({x["labels"]["alertname"] for x in json.load(sys.stdin) if x["labels"]["alertname"] in ("SecurityScanStale","ClamavScanStale","ContainerExporterStale")}); print(" ".join(a) or "none")')"
check host.auto-update-timer '^active active$' "$(systemctl is-active auto-update.timer image-cleanup.timer | xargs)"
check host.host-guard-persisted '^1$' "$(grep -c '^-A INPUT -i br-+ -j HOST-GUARD$' /etc/iptables/rules.v4 2>/dev/null || sudo -n grep -c '^-A INPUT -i br-+ -j HOST-GUARD$' /etc/iptables/rules.v4)"
check host.backup-rest '^active append-only beefy-only$' "$(systemctl is-active beefy-backup-rest.service) $(systemctl show -p ExecStart --value beefy-backup-rest.service | grep -q -- '--append-only' && echo append-only || echo NOT-append-only) $([ "$(systemctl show -p IPAddressAllow --value beefy-backup-rest.service)" = 192.168.1.102/32 ] && echo beefy-only || echo open)"
check host.backup-timers '^active active active$' "$(systemctl is-active fastpi-backup.timer fastpi-restore-test.timer beefy-repo-maint.timer | xargs)"
check host.textfile-perms '^pi:65046 2775$' "$(stat -c '%U:%g %a' /var/lib/node-exporter/textfile)"
check host.root-scripts '^0$' "$("$(dirname "${BASH_SOURCE[0]}")/../install-root-scripts.sh" --check)"
