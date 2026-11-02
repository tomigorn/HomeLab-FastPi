#!/usr/bin/env bash
# Installs the scratch bind mount (root-owned script copy, system unit at boot, user drop-in for the next claude-remote restart) and the 04:00 restart guard. Idempotent.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
"$HERE/../../Docker/_global/install-root-scripts.sh"
sudo install -o root -g root -m 0644 "$HERE/claude-scratch.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable claude-scratch.service
install -d "$HOME/.config/systemd/user/claude-remote.service.d"
install -m 0644 "$HERE/claude-remote-scratch.conf" "$HOME/.config/systemd/user/claude-remote.service.d/scratch.conf"
ln -sfn "$HERE/claude-remote-safe-restart" "$HOME/.local/bin/claude-remote-safe-restart"
install -m 0644 "$HERE/claude-remote-restart.service" "$HERE/claude-remote-restart.timer" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable claude-remote-restart.timer
echo "installed; active from the next claude-remote restart (04:00 when idle) or boot"
