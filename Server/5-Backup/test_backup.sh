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

# A second run while one holds the lock leaves the running backup's stage alone and reports status 3.
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/stage"; touch "$T/stage/dump"
ENVS=(STAGE="$T/stage" PROM="$T/prom" LOCK="$T/lock" BEEFY_TCP=/dev/tcp/127.0.0.1/9)
exec 8>"$T/lock"; flock 8
env "${ENVS[@]}" "$HERE/backup.sh" > "$T/out" 2>&1; rc=$?
[[ $rc == 0 && -e $T/stage/dump ]] && ok "second instance keeps the running stage" || bad "second instance keeps the running stage" "rc=$rc $(cat "$T/out")"
grep -qx 'backup_last_status 3' "$T/prom" && ok "already running is status 3" || bad "already running is status 3" "$(cat "$T/prom" 2>/dev/null)"
exec 8>&-
printf '%s\n' 'backup_last_success_timestamp_seconds 1234' > "$T/prom"
env "${ENVS[@]}" "$HERE/backup.sh" > "$T/out" 2>&1; rc=$?
[[ $rc == 0 && ! -e $T/stage ]] && grep -qx 'backup_last_status 2' "$T/prom" && ok "lock owner with beefy asleep: status 2, stage removed" || bad "lock owner with beefy asleep: status 2, stage removed" "rc=$rc $(cat "$T/out" "$T/prom")"
grep -qx 'backup_last_success_timestamp_seconds 1234' "$T/prom" && ok "last success kept" || bad "last success kept"

echo "passed $PASS, failed $FAIL"
[[ $FAIL == 0 ]]
