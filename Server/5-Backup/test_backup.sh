#!/usr/bin/env bash
# Checks what backup.sh backs up (its --list plan). Usage: ./test_backup.sh
HERE=$(cd "$(dirname "$0")" && pwd)
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }

L=$("$HERE/backup.sh" --list) || bad "--list runs without root or beefy"
V=/var/lib/docker/volumes
for want in \
    "sqlite /home/pi/Projects/Docker/Audiobook-Requests/config/db.sqlite" \
    "sqlite /mnt/seagate-red/sabnzbd/config/admin/history1.db" \
    "sqlite /mnt/seagate-red/prowlarr/config/prowlarr.db" \
    "sqlite /home/pi/Projects/Docker/Home-Assistant/config/home-assistant_v2.db" \
    "path /mnt/seagate-red/prowlarr/config" \
    "path /home/pi/backups/tower-flash" \
    "path $V/mouse_mousehole/_data" \
    "path $V/mouse_port-updater-data/_data" \
    "path $V/mouse_gluetun-data/_data" \
    "path $V/monitoring__grafana_alertmanager_data/_data" \
    "path /var/lib/abr-bar" \
    "path /home/pi/Projects" \
    "exclude /mnt/seagate-red/prowlarr/config/logs" \
    "exclude /mnt/seagate-red/prowlarr/config/logs.db*"; do
    grep -qxF "$want" <<<"$L" && ok "plan: $want" || bad "plan: $want"
done
! grep -qx "path /home/pi/backups" <<<"$L" && ok "rest of ~/backups stays out" || bad "rest of ~/backups stays out"

echo "passed $PASS, failed $FAIL"
[[ $FAIL == 0 ]]
