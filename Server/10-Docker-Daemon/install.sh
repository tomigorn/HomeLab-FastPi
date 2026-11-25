#!/usr/bin/env bash
# Install the docker.service drop-in (takes effect at the next docker start, i.e. the next boot). Never restarts docker.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
sudo install -d -m 0755 /etc/systemd/system/docker.service.d
sudo install -m 0644 "$HERE/docker.service.d/require-disks.conf" /etc/systemd/system/docker.service.d/require-disks.conf
sudo systemctl daemon-reload
systemctl show docker -p RequiresMountsFor
