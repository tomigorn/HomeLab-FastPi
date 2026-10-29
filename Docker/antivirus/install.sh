#!/usr/bin/env bash
# Install the ClamAV scan units (nightly new-files, nightly-resumable whole-host) on fastpi. Idempotent.
set -euo pipefail
HERE=/home/pi/Projects/Docker/antivirus
sudo install -d -o pi -g 65046 -m 2775 /var/lib/node-exporter/textfile
sudo install -d -m 0755 /var/lib/clamav-scan
sudo install -m 0644 "$HERE"/systemd/clamav-{scan,hostscan}.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now clamav-scan.timer clamav-hostscan.timer
systemctl list-timers "clamav-*.timer" --no-pager
echo "Run once now: sudo systemctl start clamav-scan.service; journalctl -u clamav-scan -n 20"
