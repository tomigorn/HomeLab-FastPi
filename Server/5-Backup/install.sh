#!/usr/bin/env bash
# Install the backup scripts and units on fastpi. Idempotent. Needs /root/.config/restic/{fastpi.pass,beefy_ed25519,known_hosts} (see README); beefy's repo: ./setup-beefy-repo.sh first.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
V=0.19.1
SUM=a5f64aaab53d51e311fa3829124c5b703f2d14cf187d8640b6be3b2b49376465
RV=0.14.0
RSUM=cef139cbe8b27b16bda731d17f093b0aa466b8c60b136c12d78b6f2bff3daf22
if [ "$(restic version 2>/dev/null | awk '{print $2}')" != "$V" ]; then
    tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/r.bz2" "https://github.com/restic/restic/releases/download/v$V/restic_${V}_linux_arm64.bz2"
    echo "$SUM  $tmp/r.bz2" | sha256sum -c -
    bunzip2 "$tmp/r.bz2"
    sudo install -m 0755 "$tmp/r" /usr/local/bin/restic
    rm -rf "$tmp"
fi
if ! /usr/local/bin/rest-server --version 2>/dev/null | grep -q "rest-server $RV "; then
    tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/rs.tgz" "https://github.com/restic/rest-server/releases/download/v$RV/rest-server_${RV}_linux_arm64.tar.gz"
    echo "$RSUM  $tmp/rs.tgz" | sha256sum -c -
    tar -xzf "$tmp/rs.tgz" -C "$tmp"
    sudo install -m 0755 "$tmp/rest-server_${RV}_linux_arm64/rest-server" /usr/local/bin/rest-server
    rm -rf "$tmp"
fi
sudo install -m 0750 -o root -g root "$HERE/backup.sh" /usr/local/sbin/fastpi-backup
sudo install -m 0750 -o root -g root "$HERE/restore-test.sh" /usr/local/sbin/fastpi-restore-test
sudo install -m 0755 -o root -g root "$HERE/beefy-repo-maint.sh" /usr/local/sbin/beefy-repo-maint
sudo install -m 0644 "$HERE/fastpi-backup.service" "$HERE/fastpi-backup.timer" "$HERE/fastpi-restore-test.service" "$HERE/fastpi-restore-test.timer" \
    "$HERE/beefy-backup-rest.service" "$HERE/beefy-repo-maint.service" "$HERE/beefy-repo-maint.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fastpi-backup.timer fastpi-restore-test.timer beefy-repo-maint.timer
if sudo test -s /etc/beefy-backup-rest/htpasswd; then sudo systemctl enable beefy-backup-rest.service; sudo systemctl restart beefy-backup-rest.service; fi
systemctl list-timers fastpi-backup.timer fastpi-restore-test.timer beefy-repo-maint.timer --no-pager
