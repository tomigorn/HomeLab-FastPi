#!/usr/bin/env bash
# Install the persistent-journal drop-in on fastpi and move the running journal to disk. Idempotent, no reboot.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
sudo install -d -m 0755 /etc/systemd/journald.conf.d
sudo install -m 0644 "$HERE/50-persistent.conf" /etc/systemd/journald.conf.d/50-persistent.conf
sudo systemctl restart systemd-journald
sudo journalctl --flush
systemd-analyze cat-config systemd/journald.conf | grep -E '^Storage='
journalctl --header | grep -m1 'File path'
