#!/usr/bin/env bash
# Installs claude-here: script and completion links, root-owned batch settings, template unit (scratch drop-in: Server/8-Claude-Scratch/install.sh), reap timer, the two always-on instances enabled at boot. Idempotent; starts and stops no session.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
U=$HOME/.config/systemd/user
ln -sfn "$HERE/claude-here" "$HOME/.local/bin/claude-here"
install -d "$HOME/.local/share/bash-completion/completions" "$HOME/.config/fish/completions"
ln -sfn "$HERE/claude-here.bash" "$HOME/.local/share/bash-completion/completions/claude-here"
ln -sfn "$HERE/claude-here.fish" "$HOME/.config/fish/completions/claude-here.fish"
sudo install -d -o root -g root -m 0755 /etc/claude-here
sudo install -o root -g root -m 0644 "$HERE/batch-settings.json" /etc/claude-here/batch-settings.json
install -m 0644 "$HERE/claude-remote@.service" "$HERE/claude-here-reap.service" "$HERE/claude-here-reap.timer" "$U/"
systemctl --user daemon-reload
systemctl --user enable --now claude-here-reap.timer
systemctl --user enable 'claude-remote@batch:-home-pi-batch.service'
# One Remote Control per folder: the template instance for ~ only once the old unit is gone (README "Migration").
systemctl --user is-enabled --quiet claude-remote.service 2>/dev/null || systemctl --user enable 'claude-remote@auto:-home-pi.service'
echo "installed: claude-here, completions, /etc/claude-here/batch-settings.json, claude-remote@.service, claude-here-reap.timer"
echo "  next: claude-here --list"
