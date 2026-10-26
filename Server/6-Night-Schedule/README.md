# 6 - Night schedule on fastpi

All recurring jobs run 22:00-06:00 (low tariff), nothing 02:00-03:00 (DST), times `Europe/Zurich`. The live pollers stay live: monitoring, dead-man pings, scrapes, dynamic DNS, `security-access` (5 min), `security-av-hits` (15 min), `container-exporter`, `authentik-app-cache`, `usage-collector`.

| Job | Was | Now |
|---|---|---|
| `security-code-scan` | hourly :17 | daily 03:40 (SBOM budget 20 Docker Hub + 100 others per run) |
| `apt-daily` | 06/18 h + ≤12 h | 03:35 (+≤5 min) |
| `apt-daily-upgrade` | 06:00 + ≤60 min | 05:15 (+≤5 min) |
| `man-db` | daily + ≤12 h | 05:25 |
| `systemd-tmpfiles-clean` | 1 day after boot | 05:28 |
| `/etc/crontab` cron.daily / weekly (Sun) / monthly (1st) | 06:25 / 06:47 / 06:52 | 05:32 / 05:44 / 05:46 (rkhunter, chkrootkit stay daily) |
| `security-av` | 04:20, 05:40, 06:40 | 04:20, 05:40, 05:50 |

`security-av` never wakes beefy or tower (`fetch_nowake`): a host the Waker sees down is skipped. beefy is held up 03:58-04:45 (`HomeLab-BeefyServer`, `Server/9-Night-Schedule.md`).

Install: `Server/6-Night-Schedule/install.sh` (drop-ins in `dropins/`, `/etc/crontab` times). Units of the security scan: `Server/4-Security-Monitoring/install.sh`. Tests: `python3 Server/4-Security-Monitoring/test_security_scan.py`.
