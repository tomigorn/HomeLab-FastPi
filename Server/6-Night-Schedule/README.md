# 6 - Night schedule on fastpi

All recurring jobs run 22:00-06:00 (low tariff), nothing 02:00-03:00 (DST), times `Europe/Zurich`. The live pollers stay live: monitoring, dead-man pings, scrapes, dynamic DNS, `security-access` (5 min), `security-av-hits` (15 min), `container-exporter`, `authentik-app-cache`, `usage-collector`, `beefy-night-downloads-poll` (5 min, only while beefy is up).

| Job | Was | Now |
|---|---|---|
| `security-code-scan` | hourly :17 | daily 03:40 (SBOM budget 20 Docker Hub + 100 others per run) |
| `apt-daily` | 06/18 h + ≤12 h | 03:35 (+≤5 min) |
| `apt-daily-upgrade` | 06:00 + ≤60 min | 05:15 (+≤5 min) |
| `man-db` | daily + ≤12 h | 05:25 |
| `systemd-tmpfiles-clean` | 1 day after boot | 05:28 |
| `/etc/crontab` cron.daily / weekly (Sun) / monthly (1st) | 06:25 / 06:47 / 06:52 | 05:32 / 05:44 / 05:46 (rkhunter, chkrootkit stay daily) |
| `security-av` | 04:20, 05:40, 06:40 | 04:20, 05:40, 05:50 |
| `clamav-hostscan` (whole-host ClamAV, `Docker/antivirus/README.md`) | Sun 01:30, ran ~12 h into the day | timer 22:30 nightly, scans only 22:00-06:00 and all day Sunday, idle priority, resumes where it stopped (one pass a week, ~289 000 files; stops at 06:00 without waiting for 02:00-03:00, DST-safe) |
| `fastpi-restore-test` | new | first Tuesday of the month 04:33, inside beefy's 03:58-04:45 window, never wakes beefy (`Server/5-Backup/README.md` "Monthly restore test") |
| `beefy-repo-maint` | new | 05:07 daily: retention of beefy's backup repo on fastpi (local, beefy not needed), prune Sunday, check Wednesday (`Server/5-Backup/README.md` "beefy → fastpi") |
| `beefy-backup` (beefy) | new | 04:26 on beefy: backup to fastpi's append-only server, inside the window (`HomeLab-BeefyServer`, `Server/10-Backup.md`) |
| `beefy-night-downloads-wake` | new | 22:05, wakes beefy only when downloads wait for the night (`Docker/Beefy-Waker/README.md` "Night downloads wake") |
| `night-search` (beefy) | new | 04:17 on beefy: episodes aired and films released recently without a file, plus 5+5 cutoff-unmet titles, max 200 Treasure Maps searches (`HomeLab-BeefyServer`, `Docker/Movie-Downloads/README.md` "Upgrades") |
| `subtitle-check` (beefy) | new | 04:21 on beefy: subtitles changed since the last run (SSD only) checked for broken encoding, unambiguous ones repaired; findings reach the 06:30 digest through the queue-watchdog file (`beefy_watchdog.prom`, kinds `subtitle_repaired`, `subtitle_suspect`) (`HomeLab-BeefyServer`, `Docker/Movie-Downloads/README.md` "Subtitle check") |

All fixed-time jobs on fastpi, in night order (`systemctl list-timers` is the truth):

| Time | Timer | What (doc) |
|---|---|---|
| 22:05 | `beefy-night-downloads-wake` | wakes beefy for waiting night downloads (`Docker/Beefy-Waker`) |
| 22:30 | `clamav-hostscan` | whole-host ClamAV, resumable (`Docker/antivirus`) |
| 03:10 | `auto-update` | tiered image updates with rollback (`Docker/_global/UPDATE-RUNBOOK.md`) |
| 03:35 / 05:15 / 05:25 / 05:28 | `apt-daily` / `apt-daily-upgrade` / `man-db` / `systemd-tmpfiles-clean` | drop-ins in `dropins/` |
| 03:40 | `security-code-scan` | SBOMs (`Server/4-Security-Monitoring`) |
| 03:55 | `beefy-maintenance-wake` | wakes beefy for its 03:58-04:45 window (`Docker/Beefy-Waker`) |
| 04:00 | `claude-remote-restart` (user) | postponed while a session is busy (`Server/3-Claude-Remote-Control.md`) |
| 04:02 / 04:05 (+≤3 min) / 04:10 | `security-dt` / `security-scan` / `security-image-scan` | `Server/4-Security-Monitoring` |
| Sun 04:05 | `security-audit` | `Server/4-Security-Monitoring` |
| 04:06 | `fastpi-backup` | restic to beefy (`Server/5-Backup`) |
| 04:12 | `usage-collector` | `Docker/grafana` |
| 04:20, 05:40, 05:50 | `security-av` | `Server/4-Security-Monitoring` |
| first Tue 04:33 | `fastpi-restore-test` | `Server/5-Backup` |
| 05:00 | `clamav-scan` | new-files scan (`Docker/antivirus`) |
| 05:07 | `beefy-repo-maint` | `Server/5-Backup` |
| 05:07 (+≤10 min) | `crowdsec-autoupdate` | `Docker/CrowdSec` |
| Sun 05:30 | `image-cleanup` | old images, rollback tags kept 14 d (`Docker/_global/UPDATE-RUNBOOK.md`) |
| 05:32 / 05:44 / 05:46 | cron daily / weekly / monthly | `/etc/crontab` |
| 05:37 | `subscription-alerts` | Telegram warnings (`Docker/grafana`) |
| 05:43 | `mam-points` | `Docker/_global/scripts/README.md` |
| 05:50 | `status-exporter-daily` | certs, domains (`Docker/grafana`) |

Pollers (every few minutes, any time): `security-access`, `security-av-hits`, `beefy-idle-pull`, `beefy-night-downloads-poll`, `status-exporter`, `smart-exporter` (30 min, never wakes a parked disk), `crowdsec-exporter`, `abr-bar-usage` (1 min), `avatar-sync` (only while a pick is pending), `tower-flash-backup` (user, hourly).

`security-av` never wakes beefy or tower (`fetch_nowake`): a host the Waker sees down is skipped. beefy is held up 03:58-04:45 (`HomeLab-BeefyServer`, `Server/9-Night-Schedule.md`).

Install: `Server/6-Night-Schedule/install.sh` (drop-ins in `dropins/`, `/etc/crontab` times). Units of the security scan: `Server/4-Security-Monitoring/install.sh`. Tests: `python3 Server/4-Security-Monitoring/test_security_scan.py`.
