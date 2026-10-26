#!/usr/bin/env bash
# Install the night-schedule drop-ins on fastpi and move cron.daily/weekly/monthly into the night. Idempotent.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
for d in "$HERE"/dropins/*.d; do
    u=$(basename "$d")
    sudo install -d -m 0755 "/etc/systemd/system/$u"
    sudo install -m 0644 "$d"/night-window.conf "/etc/systemd/system/$u/night-window.conf"
done
# /etc/crontab is a package conffile: only the minute/hour of the three run-parts lines change.
sudo sed -i -E \
    -e 's/^25 [0-9]+(\s+\* \* \*\s+root\s+test -x \/usr\/sbin\/anacron \|\| \{ cd \/ && run-parts --report \/etc\/cron\.daily)/32 5\1/' \
    -e 's/^47 [0-9]+(\s+\* \* 7\s+root\s+test -x \/usr\/sbin\/anacron \|\| \{ cd \/ && run-parts --report \/etc\/cron\.weekly)/44 5\1/' \
    -e 's/^52 [0-9]+(\s+1 \* \*\s+root\s+test -x \/usr\/sbin\/anacron \|\| \{ cd \/ && run-parts --report \/etc\/cron\.monthly)/46 5\1/' \
    /etc/crontab
sudo systemctl daemon-reload
systemctl list-timers apt-daily.timer apt-daily-upgrade.timer man-db.timer systemd-tmpfiles-clean.timer --no-pager
grep -E 'run-parts --report /etc/cron\.(daily|weekly|monthly)' /etc/crontab
