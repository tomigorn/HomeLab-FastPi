#!/usr/bin/env bash
# Installs the scratch bind mount: root-owned script copy, system unit (boot), user drop-in (switch at the next claude-remote restart). Idempotent.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
"$HERE/../../Docker/_global/install-root-scripts.sh"
sudo install -o root -g root -m 0644 "$HERE/claude-scratch.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable claude-scratch.service
install -d "$HOME/.config/systemd/user/claude-remote.service.d"
install -m 0644 "$HERE/claude-remote-scratch.conf" "$HOME/.config/systemd/user/claude-remote.service.d/scratch.conf"
systemctl --user daemon-reload
echo "installed; active from the next claude-remote restart (04:00 when idle) or boot"
