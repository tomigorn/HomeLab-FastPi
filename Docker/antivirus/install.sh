#!/usr/bin/env bash
# Install the nightly ClamAV scan units on fastpi. Idempotent.
set -euo pipefail
HERE=/home/pi/Projects/Docker/antivirus
sudo install -d -o pi -g pi -m 0755 /var/lib/node-exporter/textfile
sudo install -d -m 0755 /var/lib/clamav-scan
sudo install -m 0644 "$HERE"/systemd/clamav-scan.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now clamav-scan.timer
systemctl list-timers clamav-scan.timer --no-pager
echo "Run once now: sudo systemctl start clamav-scan.service; journalctl -u clamav-scan -n 20"
