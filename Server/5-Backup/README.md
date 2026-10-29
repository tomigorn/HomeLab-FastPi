# 5 - Nightly backup fastpi → beefy

restic, encrypted, deduplicated. `backup.sh` runs as root via `fastpi-backup.timer` at 04:06 (beefy's maintenance window, never woken for this; asleep = skipped, status 2). Limit 18 min.

| What | Detail |
|---|---|
| Repo | `sftp:buntu@beefy.homelab:/home/buntu/backups/fastpi-restic` (beefy NVMe, dir 700) |
| Key | `/root/.config/restic/beefy_ed25519`, on beefy `from="192.168.1.2",restrict,command="internal-sftp -d …"` (sftp only, not a chroot) |
| Password | `/root/.config/restic/fastpi.pass` (root 600). **Keep a copy off fastpi (password manager); without it the backup is unreadable** |
| Hosts file | `/root/.config/restic/known_hosts` pins beefy's host key |
| Retention | 7 daily, 4 weekly, 6 monthly; prune Sunday; `check --read-data-subset=1/10` Wednesday |
| Metrics | `backup.prom` (textfile): last success, status (1 ok, 0 failed, 2 skipped), bytes, errors. Alert `BackupStale` > 36 h |
| Restore test | `restore-test.sh` via `fastpi-restore-test.timer`, first Tuesday of the month 04:33 (see below) |
| Install | `./install.sh` (restic 0.19.1 pinned by sha256, scripts to `/usr/local/sbin/fastpi-backup` and `fastpi-restore-test`, units, timers) |

## Contents
- Consistent dumps: Authentik Postgres (`pg_dump -Fc`), SQLite `.backup` of Home Assistant recorder + zigbee, Grafana, Audiobookshelf, Stonks, Bitwarden, wg-easy, wg-chores, CrowdSec. Restored under `/var/lib/fastpi-backup-staging/{dumps,sqlite/<original path>}` inside the snapshot; the live DB files are excluded.
- `/home/pi/Projects` (compose, `.env`, `secrets/`, Traefik acme + dynamic config, HA config), landingpage, Unraid repo, `~/.ssh`, `~/.claude` rules + skills + memory
- `/etc`: ssh, sudoers.d, sysctl.d, iptables, docker, systemd/system, fstab, cron.d, hosts
- `/var/lib/security-scan` (no trivy cache), CrowdSec config, AdGuard data (no querylog), Portainer data
- Audiobook downloaders on the Seagate disk: `/mnt/seagate-red/qbittorrent/config` (torrent list + resume data, settings) and `/mnt/seagate-red/sabnzbd/config` (no unfinished `Downloads/`, no logs), since 2026-10-25
- Not backed up: InfluxDB and Prometheus data (3.5 GB + 1.6 GB, metrics only), media, downloads, images, `~/backups`, LoyaltyCards volumes

Size 2026-10-29: nightly snapshot 1.3 GiB; repo 31 GiB, almost all the one-off `pre-trixie` snapshot (55 GiB, tag kept by its own retention group until forgotten by hand). Nightly growth is mostly the HA recorder DB.

## Restore
```bash
sudo -i
export RESTIC_PASSWORD_FILE=/root/.config/restic/fastpi.pass RESTIC_REPOSITORY=sftp:buntu@beefy.homelab:/home/buntu/backups/fastpi-restic
export SSHC='ssh -i /root/.config/restic/beefy_ed25519 -o IdentitiesOnly=yes -o UserKnownHostsFile=/root/.config/restic/known_hosts buntu@beefy.homelab -s sftp'
restic -o sftp.command="$SSHC" snapshots
restic -o sftp.command="$SSHC" restore latest --target /restore --include /home/pi/Projects --include /var/lib/fastpi-backup-staging
```
- Authentik: `docker exec -i authentik-postgresql pg_restore -U authentik -d authentik --clean --if-exists < /restore/var/lib/fastpi-backup-staging/dumps/authentik.pgdump` (list first with `pg_restore -l`)
- SQLite DB: stop the container, copy `/restore/var/lib/fastpi-backup-staging/sqlite/<original path>` over the original, delete its `-wal`/`-shm`
- A single file: `restic … restore latest --target /restore --include <path>`

Fresh fastpi (key and password lost with it): use the password from the password manager, create a new key, add it to beefy's `authorized_keys` (same restricted line) and run the commands above.

## Monthly restore test
`restore-test.sh` (root, never touches live data), first Tuesday 04:33 inside beefy's window; beefy asleep or the backup still running after 5 min = skipped (status 2).

| Step | Fails when |
|---|---|
| `restic check --read-data-subset=5%` | any error |
| restore latest nightly (staging dumps, compose, Traefik, `Server/`, `/etc/ssh`, `/etc/systemd/system`, `/etc/iptables`) into `/var/tmp/fastpi-restore-test.*` | restore error |
| `pragma quick_check` on every staged SQLite dump | not `ok`, or no dumps |
| compare restored files with live files not modified since the snapshot | any difference |
| Authentik dump → throwaway postgres (same image, `--network none`, tmpfs, removed afterwards); users/groups/apps vs live (read-only) | restore error or 0 users |

Result: Telegram summary via `Docker/_global/scripts/oob-alert.sh`, metrics `backup-restore-test.prom` (`backup_restore_test_last_status` 1 ok / 0 failed / 2 skipped, snapshot age, restore bytes and seconds). Run now: `sudo systemctl start fastpi-restore-test`. Tests: `./test_restore_test.sh`.

Proven 2026-10-25: Authentik dump restored and listed (`pg_restore -l`, 1819 entries), `traefik.yml` identical to the live file, Bitwarden DB `integrity_check` ok.

Limit: a compromised fastpi holds the sftp key and can delete the repo (restic over sftp has no append-only mode).
