#!/usr/bin/env bash
# Install the backup script and units on fastpi. Idempotent. Needs /root/.config/restic/{fastpi.pass,beefy_ed25519,known_hosts} (see README).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
V=0.19.1
SUM=a5f64aaab53d51e311fa3829124c5b703f2d14cf187d8640b6be3b2b49376465
if [ "$(restic version 2>/dev/null | awk '{print $2}')" != "$V" ]; then
    tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/r.bz2" "https://github.com/restic/restic/releases/download/v$V/restic_${V}_linux_arm64.bz2"
    echo "$SUM  $tmp/r.bz2" | sha256sum -c -
    bunzip2 "$tmp/r.bz2"
    sudo install -m 0755 "$tmp/r" /usr/local/bin/restic
    rm -rf "$tmp"
fi
sudo install -m 0750 -o root -g root "$HERE/backup.sh" /usr/local/sbin/fastpi-backup
sudo install -m 0750 -o root -g root "$HERE/restore-test.sh" /usr/local/sbin/fastpi-restore-test
sudo install -m 0644 "$HERE/fastpi-backup.service" "$HERE/fastpi-backup.timer" "$HERE/fastpi-restore-test.service" "$HERE/fastpi-restore-test.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fastpi-backup.timer fastpi-restore-test.timer
systemctl list-timers fastpi-backup.timer fastpi-restore-test.timer --no-pager
