# Persistent journal (fastpi)

Raspberry Pi OS ships `/usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf` (`Storage=volatile`): the journal lived in RAM only and was lost at every reboot (FB-01, a month of logs lost on 2026-11-24).

| File | Live path | Effect |
|---|---|---|
| `50-persistent.conf` | `/etc/systemd/journald.conf.d/50-persistent.conf` | `Storage=persistent`, sorts after the `40-rpi-…` file |

Size limits stay in `10-hardening.conf` (`SystemMaxUse=1G`, see `Docker/_global/pi-hardening-runbook.md`).

Install (no reboot): `Server/9-Persistent-Journal/install.sh`

Check:
- `systemd-analyze cat-config systemd/journald.conf | grep '^Storage='` → last line `Storage=persistent`
- `journalctl --header | grep -m1 'File path'` → `/var/log/journal/…`
- `journalctl --list-boots` → keeps growing after a reboot
- The nightly drift check (`repo_drift.py`, kind `etc`) compares the live file with this one and reports it when a later drop-in overrides it.
