#!/usr/bin/env bash
# Install CrowdSec's host-side units on fastpi: the textfile exporter (every 5 min)
# and the daily auto-update. Idempotent.
set -euo pipefail
HERE=/home/pi/Projects/Docker/CrowdSec
sudo install -d -o pi -g 65046 -m 2775 /var/lib/node-exporter/textfile
sudo install -m 0644 "$HERE"/systemd/crowdsec-exporter.{service,timer} \
                     "$HERE"/systemd/crowdsec-autoupdate.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crowdsec-exporter.timer crowdsec-autoupdate.timer
sudo systemctl start crowdsec-exporter.service
systemctl list-timers 'crowdsec-*' --no-pager
echo "Verify: curl -s localhost:9100/metrics | grep -c '^crowdsec_'   (node-exporter is on the grafana network; or check Prometheus)"
