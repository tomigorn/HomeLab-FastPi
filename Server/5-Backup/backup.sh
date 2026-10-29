#!/usr/bin/env bash
# Nightly encrypted restic backup of fastpi to beefy (SFTP, dedicated restricted key). Runs as root from fastpi-backup.service.
# Beefy asleep: exit 0 with status 2 in the metric, never wakes it.
set -uo pipefail

CONF=/root/.config/restic
STAGE=/var/lib/fastpi-backup-staging
PROM=/var/lib/node-exporter/textfile/backup.prom
BEEFY_IP=192.168.1.102
export RESTIC_PASSWORD_FILE=$CONF/fastpi.pass
export RESTIC_REPOSITORY=sftp:buntu@beefy.homelab:/home/buntu/backups/fastpi-restic
export RESTIC_CACHE_DIR=/var/cache/restic
SSHC="ssh -i $CONF/beefy_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=10 -o UserKnownHostsFile=$CONF/known_hosts -o StrictHostKeyChecking=yes buntu@beefy.homelab -s sftp"
ERRF=/run/fastpi-backup.err
D=/home/pi/Projects/Docker
V=/var/lib/docker/volumes
SQLITE_DBS=(
    "$D/Home-Assistant/config/home-assistant_v2.db"
    "$D/Home-Assistant/config/zigbee.db"
    "$D/WireguardVPN/wg-easy-v15/wg-easy.db"
    "$D/audiobookshelf/audiobookshelf/config/absdatabase.sqlite"
    "$D/Stonks/data/stonks.db"
    "$D/bitwarden/data/db.sqlite3"
    "$V/monitoring__grafana_grafana_data/_data/grafana.db"
    "$V/crowdsec_crowdsec_data/_data/crowdsec.db"
    "$V/wg-chores_wgchores-data/_data/wgchores.db"
    "$D/Audiobook-Requests/config/db.sqlite"
    /mnt/seagate-red/sabnzbd/config/admin/history1.db
    /mnt/seagate-red/prowlarr/config/prowlarr.db
)
EXCLUDES=(
    --exclude '/home/pi/Projects/Docker/*/node_modules'
    --exclude '/home/pi/Projects/Docker/Traefik/traefik/logs'
    --exclude '/home/pi/Projects/Docker/Authentik/backups'
    --exclude '/home/pi/Projects/Docker/Home-Assistant/config/home-assistant.log*'
    --exclude '/home/pi/Projects/Docker/audiobookshelf/audiobookshelf/config/absdatabase.sqlite.*'
    --exclude '/home/pi/Projects/Docker/audiobookshelf/audiobookshelf/metadata/cache'
    --exclude '/home/pi/Projects/Docker/audiobookshelf/audiobookshelf/metadata/logs'
    --exclude '/home/pi/Projects/Docker/audiobookshelf/audiobookshelf/metadata/tmp'
    --exclude '/home/pi/Projects/Docker/audiobookshelf/audiobookshelf/metadata/streams'
    --exclude '/home/pi/Projects/Docker/Stonks/data/backups'
    --exclude "$V/adguard_adguardhome-data/_data/data/querylog.json*"
    --exclude "$V/adguard_adguardhome-data/_data/data/stats.db"
    --exclude '/var/lib/security-scan/trivy-cache'
    --exclude '/var/lib/security-scan/sbom'
    --exclude '/var/lib/security-scan/mirrors'
    --exclude '/mnt/seagate-red/sabnzbd/config/Downloads'
    --exclude '/mnt/seagate-red/sabnzbd/config/logs'
    --exclude '/mnt/seagate-red/qbittorrent/config/qBittorrent/logs'
    --exclude '/mnt/seagate-red/prowlarr/config/logs'
    --exclude '/mnt/seagate-red/prowlarr/config/logs.db*'
)
PATHS=(
    "$STAGE"
    /home/pi/Projects /home/pi/landingpage /home/pi/HomeLab-Unraid-Tower /home/pi/.ssh
    /home/pi/.claude/CLAUDE.md /home/pi/.claude/machine.md /home/pi/.claude/settings.json /home/pi/.claude/settings.local.json
    /home/pi/.claude/skills /home/pi/.claude/projects/-home-pi/memory
    /etc/ssh /etc/sudoers.d /etc/sysctl.d /etc/iptables /etc/docker /etc/systemd/system /etc/fstab /etc/cron.d /etc/hosts
    /var/lib/security-scan
    /mnt/seagate-red/qbittorrent/config /mnt/seagate-red/sabnzbd/config /mnt/seagate-red/prowlarr/config
    /home/pi/backups/tower-flash /var/lib/abr-bar
    "$V/crowdsec_crowdsec_config/_data" "$V/adguard_adguardhome-data/_data" "$V/docker_portainer_data/_data"
    "$V/mouse_mousehole/_data" "$V/mouse_port-updater-data/_data" "$V/mouse_gluetun-data/_data"
    "$V/monitoring__grafana_alertmanager_data/_data"
)

if [ "${1:-}" = --list ]; then
    for db in "${SQLITE_DBS[@]}"; do echo "sqlite $db"; done
    for p in "${PATHS[@]}"; do echo "path $p"; done
    for ((i=1; i<${#EXCLUDES[@]}; i+=2)); do echo "exclude ${EXCLUDES[i]}"; done
    exit 0
fi

R() { restic -o sftp.command="$SSHC" "$@"; }

log() { echo "backup: $*"; }
STATUS=0 BYTES=0 ADDED=0 ERRORS=0
write_metric() {
    local now ok
    now=$(date +%s)
    ok=$(grep -s '^backup_last_success_timestamp_seconds ' "$PROM" | awk '{print $2}')
    [ "$STATUS" = 1 ] && ok=$now
    cat > "$PROM.tmp" <<EOM
# TYPE backup_last_run_timestamp_seconds gauge
backup_last_run_timestamp_seconds $now
# TYPE backup_last_success_timestamp_seconds gauge
backup_last_success_timestamp_seconds ${ok:-0}
# TYPE backup_last_status gauge
# 1 ok, 0 failed, 2 skipped (beefy asleep)
backup_last_status $STATUS
# TYPE backup_last_bytes_processed gauge
backup_last_bytes_processed $BYTES
# TYPE backup_last_bytes_added gauge
backup_last_bytes_added $ADDED
# TYPE backup_last_errors gauge
backup_last_errors $ERRORS
EOM
    chmod 644 "$PROM.tmp"; mv "$PROM.tmp" "$PROM"
}
cleanup() { rm -rf "$STAGE"; write_metric; }
trap cleanup EXIT
trap 'log "terminated"; exit 1' TERM INT

exec 9>/run/fastpi-backup.lock
flock -n 9 || { log "already running"; STATUS=2; exit 0; }

if ! timeout 5 bash -c "</dev/tcp/$BEEFY_IP/22" 2>/dev/null; then
    log "beefy unreachable (asleep), skipped"
    STATUS=2
    exit 0
fi

umask 077
rm -rf "$STAGE"; install -d -m 700 "$STAGE" "$STAGE/sqlite" "$STAGE/dumps"
EXCL=(--exclude-caches)
for db in "${SQLITE_DBS[@]}"; do
    [ -f "$db" ] || { log "missing $db"; ERRORS=$((ERRORS+1)); continue; }
    install -d -m 700 "$STAGE/sqlite$(dirname "$db")"
    if ! sqlite3 "$db" ".timeout 30000" ".backup '$STAGE/sqlite$db'"; then
        log "sqlite backup failed: $db"; ERRORS=$((ERRORS+1)); continue
    fi
    EXCL+=(--exclude "$db" --exclude "$db-wal" --exclude "$db-shm")
done
EXCL+=("${EXCLUDES[@]}")

if ! docker exec authentik-postgresql sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$STAGE/dumps/authentik.pgdump" || [ ! -s "$STAGE/dumps/authentik.pgdump" ]; then
    log "authentik pg_dump failed"; ERRORS=$((ERRORS+1))
fi

EXISTING=(); for p in "${PATHS[@]}"; do [ -e "$p" ] && EXISTING+=("$p"); done

OUT=$(R backup --json --one-file-system --host fastpi --tag nightly "${EXCL[@]}" "${EXISTING[@]}" 2>"$ERRF")
RC=$?
SUM=$(printf '%s\n' "$OUT" | grep '"message_type":"summary"' | tail -1)
if [ -n "$SUM" ]; then
    BYTES=$(jq -r '.total_bytes_processed' <<<"$SUM"); ADDED=$(jq -r '.data_added' <<<"$SUM")
fi
# rc 3 = some source files unreadable (vanished temp files); snapshot exists
if [ $RC -ne 0 ] && [ $RC -ne 3 ]; then
    log "restic backup failed rc=$RC: $(tail -3 "$ERRF")"; ERRORS=$((ERRORS+1)); STATUS=0; exit 1
fi
[ $RC -eq 3 ] && { log "some files unreadable: $(head -3 "$ERRF")"; ERRORS=$((ERRORS+1)); }
log "snapshot done: processed=$BYTES added=$ADDED"

R forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --group-by host,tags || { log "forget failed"; ERRORS=$((ERRORS+1)); }
DOW=$(date +%u)
if [ "$DOW" = 7 ]; then R prune || { log "prune failed"; ERRORS=$((ERRORS+1)); }; fi
if [ "$DOW" = 3 ]; then R check --read-data-subset=1/10 || { log "check failed"; ERRORS=$((ERRORS+1)); }; fi

[ "$ERRORS" -eq 0 ] && STATUS=1 || STATUS=0
log "finished status=$STATUS errors=$ERRORS"
[ "$STATUS" = 1 ]
