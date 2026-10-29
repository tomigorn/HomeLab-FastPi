# 5 - Backups: fastpi → beefy, beefy → fastpi

restic, encrypted, deduplicated, both ways. fastpi → beefy below; beefy → fastpi (append-only) in "beefy → fastpi".

| When | Job | Host |
|---|---|---|
| 04:06 | `fastpi-backup` → beefy | fastpi |
| 04:26 | `beefy-backup` → fastpi (`HomeLab-BeefyServer` `Server/10-Backup.md`) | beefy |
| 05:07 | `beefy-repo-maint`: retention of beefy's repo | fastpi |
| first Tue 04:33 | `fastpi-restore-test`: both repos | fastpi |

## fastpi → beefy

 `backup.sh` runs as root via `fastpi-backup.timer` at 04:06 (beefy's maintenance window, never woken for this; asleep = skipped, status 2). Limit 18 min.

| What | Detail |
|---|---|
| Repo | `sftp:buntu@beefy.homelab:/home/buntu/backups/fastpi-restic` (beefy NVMe, dir 700) |
| Key | `/root/.config/restic/beefy_ed25519`, on beefy `from="192.168.1.2",restrict,command="internal-sftp -d …"` (sftp only, not a chroot) |
| Password | `/root/.config/restic/fastpi.pass` (root 600). **Keep a copy off fastpi (password manager); without it the backup is unreadable** |
| Hosts file | `/root/.config/restic/known_hosts` pins beefy's host key |
| Retention | 7 daily, 4 weekly, 6 monthly; prune Sunday; `check --read-data-subset=1/10` Wednesday |
| Metrics | `backup.prom` (textfile): last success, status (1 ok, 0 failed, 2 skipped: beefy asleep, 3 skipped: a backup already running; a second run never touches the running one's stage), bytes, errors. Alert `BackupStale` > 36 h |
| Restore test | `restore-test.sh` via `fastpi-restore-test.timer`, first Tuesday of the month 04:33 (see below) |
| Install | `./install.sh` (restic 0.19.1 and rest-server 0.14.0 pinned by sha256, scripts to `/usr/local/sbin/`, units, timers) |
| Tests | `./test_backup.sh` (what is backed up, `backup.sh --list`; lock and stage of a second run), `./test_restore_test.sh`, `./test_beefy_repo_maint.sh` |

### Contents (`./backup.sh --list`)
- Consistent dumps: Authentik Postgres (`pg_dump -Fc`), SQLite `.backup` of Home Assistant recorder + zigbee, Grafana, Audiobookshelf, Stonks, Bitwarden, wg-easy, wg-chores, CrowdSec, Audiobook-Requests, SABnzbd history, Prowlarr (mouse). Restored under `/var/lib/fastpi-backup-staging/{dumps,sqlite/<original path>}` inside the snapshot; the live DB files are excluded.
- `/home/pi/Projects` (compose, `.env`, `secrets/`, Traefik acme + dynamic config, HA config), landingpage, Unraid repo, `~/.ssh`, `~/.claude` rules + skills + memory
- `/etc`: ssh, sudoers.d, sysctl.d, iptables, docker, systemd/system, fstab, cron.d, hosts
- `/var/lib/security-scan` (no trivy cache), CrowdSec config, AdGuard data (no querylog), Portainer data
- Audiobook downloaders on the Seagate disk: `/mnt/seagate-red/qbittorrent/config` (torrent list + resume data, settings) and `/mnt/seagate-red/sabnzbd/config` (no unfinished `Downloads/`, no logs), since 2026-10-25; `/mnt/seagate-red/prowlarr/config` (no logs), since 2026-10-29
- Since 2026-10-29: `~/backups/tower-flash` (tower's `/boot/config` copies), volumes `mouse_mousehole`, `mouse_port-updater-data`, `mouse_gluetun-data`, Alertmanager data (silences), `/var/lib/abr-bar`
- Not backed up: InfluxDB and Prometheus data (3.5 GB + 1.6 GB, metrics only), media, downloads, images, the rest of `~/backups` (one-off copies), LoyaltyCards volumes, beefy's repo (`/var/lib/beefy-backup`)

Size 2026-10-29: nightly snapshot 1.4 GiB; repo 1.5 GiB after the one-off `pre-trixie` snapshot (55 GiB) was forgotten and pruned (30 GiB freed). Nightly growth is mostly the HA recorder DB.

### Restore
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

## beefy → fastpi (append-only)

beefy pushes at 04:26 to `rest-server` on fastpi; it can add snapshots, never delete or overwrite them (tested: `forget` → 403). A compromised beefy cannot wipe its history.

| What | Detail |
|---|---|
| Server | `beefy-backup-rest.service`: `/usr/local/bin/rest-server --append-only --private-repos`, TLS, `192.168.1.2:8009`, user `beefy-backup`, systemd sandbox, `IPAddressAllow=192.168.1.102` (only beefy; fastpi itself and every other LAN/VPN host are dropped). No firewall change, no Docker |
| Repo | `/var/lib/beefy-backup/beefy` (NVMe, 700, owner `beefy-backup`) |
| Login / TLS | `/etc/beefy-backup-rest/{htpasswd,tls.crt,tls.key}` (bcrypt user `beefy`; self-signed P-256 cert, 10 years, pinned on beefy) |
| Keys | two restic keys: fastpi `/root/.config/restic/beefy-repo.pass` (**keep a copy in the password manager**), beefy its own |
| Setup | `./setup-beefy-repo.sh` as pi, once (idempotent; creates user, cert, login, repo, keys, copies beefy's credentials over ssh; prints no secret), then `./install.sh` |
| Retention | `beefy-repo-maint.sh` (05:07, user `beefy-backup` like rest-server, so its locks/packs stay readable for it; password via `LoadCredential=`, rest-server cannot see `/run/credentials`; refuses to run as root; sandbox as the REST unit, no network; metric written to `/var/lib/beefy-repo-maint/`, published by a root `ExecStopPost`): everything from the last 30 days, then 7 daily, 4 weekly, 6 monthly; prune Sunday; check 10 % Wednesday |
| Future-dated snapshots | beefy picks snapshot times itself (`restic backup --time`). Any snapshot (any host) more than 1 h ahead, or with an unreadable time: forget and prune are refused, `beefy_backup_future_snapshots` > 0, alert `BeefyBackupSnapshotInFuture` (Telegram + email, any time). Such snapshots never count as the newest. Fix: check them (`restic snapshots`), `restic forget <id>` as root |
| Metrics | `beefy-backup.prom`, read from the repo itself: newest snapshot time/bytes, count, future-dated count, repo bytes, maint status; every value checked numeric. Alerts `BeefyBackupStale` (> 36 h), `BeefyBackupRepoMaintFailed`, `BeefyBackupSnapshotInFuture`; beefy pages failures itself (Telegram) |
| Contents | beefy `Server/10-Backup.md` (`beefy-backup.sh --list`) |

Size 2026-10-29: first snapshot 2.7 GiB processed (DT5 dump 2.0 GiB), repo 0.94 GiB, 22 s.

```bash
sudo -i
export RESTIC_REPOSITORY=/var/lib/beefy-backup/beefy RESTIC_PASSWORD_FILE=/root/.config/restic/beefy-repo.pass
restic snapshots
restic restore latest --target /restore --include /var/lib/beefy-backup-staging --include /srv/appdata/seerr
```
Then copy to beefy and follow beefy `Server/10-Backup.md` "Restore". fastpi lost: beefy's data is still live on beefy; set up again with `setup-beefy-repo.sh`.

## Monthly restore test
`restore-test.sh` (root, never touches live data), first Tuesday 04:33 inside beefy's window. fastpi's repo: beefy asleep or the backup still running after 5 min = that part skipped (status 2). beefy's repo is local and always tested, read-only with `--no-lock` (root-owned lock files would be unreadable for rest-server and fail a concurrent beefy backup).

| Step | Fails when |
|---|---|
| `restic check --read-data-subset=5%` | any error |
| restore latest nightly (staging dumps, compose, Traefik, `Server/`, `/etc/ssh`, `/etc/systemd/system`, `/etc/iptables`) into `/var/tmp/fastpi-restore-test.*` | restore error |
| `pragma quick_check` on every staged SQLite dump | not `ok`, or no dumps |
| compare restored files with live files not modified since the snapshot | any difference |
| Authentik dump → throwaway postgres (same image, `--network none`, tmpfs, removed afterwards); users/groups/apps vs live (read-only) | restore error or 0 users |
| beefy repo: `check --read-data-subset=5%`, restore staging dumps, `/etc/fstab`, compose, Jellyfin plugin configs, DT5 keys | any error, no snapshot |
| beefy: `quick_check` of every SQLite dump; Seerr, Jellyfin, Radarr, Sonarr present | not `ok` or missing |
| beefy: DT5 dump `pg_restore -l` (throwaway container, no network); KEK JSON has a primary key | unreadable / invalid |

Result: Telegram summary via `Docker/_global/scripts/oob-alert.sh`, metrics `backup-restore-test.prom` (`backup_restore_test_last_status` 1 ok / 0 failed / 2 fastpi part skipped, `..._last_success_timestamp_seconds`, `..._beefy_status`, snapshot ages, restore bytes and seconds). Alerts `BackupRestoreTestFailed` (status 0), `BackupRestoreTestStale` (no success for 40 days). Run now: `sudo systemctl start fastpi-restore-test`. Tests: `./test_restore_test.sh`.

Proven 2026-10-25: Authentik dump restored and listed (`pg_restore -l`, 1819 entries), `traefik.yml` identical to the live file, Bitwarden DB `integrity_check` ok.

Limit: a compromised fastpi holds the sftp key and can delete its own repo on beefy (restic over sftp has no append-only mode; beefy's repo on fastpi is append-only). Offsite copy: still open.
