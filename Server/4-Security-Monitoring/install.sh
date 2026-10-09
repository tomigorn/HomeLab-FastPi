#!/usr/bin/env bash
# Install the security monitoring units and the pre-commit hook on fastpi.
#
# Idempotent: safe to re-run after editing any of the files it copies.
set -euo pipefail

REPO=/home/pi/Projects
HERE="$REPO/Server/4-Security-Monitoring"

echo "==> state and metric directories"
sudo install -d -o pi -g pi -m 0755 /var/lib/security-scan
# node-exporter reads this directory; the scan writes to it as the pi user.
sudo install -d -o pi -g pi -m 0755 /var/lib/node-exporter/textfile

echo "==> gitleaks binary"
if ! command -v gitleaks >/dev/null 2>&1; then
    V=8.30.1
    case "$(uname -m)" in
        aarch64|arm64) ARCH=arm64 ;;
        x86_64|amd64)  ARCH=x64 ;;
        *) echo "unsupported arch $(uname -m)" >&2; exit 1 ;;
    esac
    tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/gl.tar.gz" \
        "https://github.com/gitleaks/gitleaks/releases/download/v${V}/gitleaks_${V}_linux_${ARCH}.tar.gz"
    tar xzf "$tmp/gl.tar.gz" -C "$tmp" gitleaks
    sudo install -m 0755 "$tmp/gitleaks" /usr/local/bin/gitleaks
    rm -rf "$tmp"
fi
gitleaks version | sed 's/^/    gitleaks /'

echo "==> pre-commit hook (via core.hooksPath, so it is version-controlled)"
# core.hooksPath rather than copying into .git/hooks: a hook that lives only in
# .git/ silently disappears on a fresh clone, and a hook that is not installed
# looks exactly like a hook that found nothing.
git -C "$REPO" config core.hooksPath .githooks
chmod +x "$REPO/.githooks/pre-commit"
echo "    core.hooksPath=$(git -C "$REPO" config core.hooksPath)"

echo "==> systemd units"
sudo install -m 0644 "$HERE"/security-scan.service "$HERE"/security-scan.timer \
                     "$HERE"/security-image-scan.service "$HERE"/security-image-scan.timer \
                     /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now security-scan.timer security-image-scan.timer

echo "==> node-exporter must expose the textfile collector"
if ! docker inspect node-exporter --format '{{join .Args " "}}' 2>/dev/null | grep -q 'collector.textfile.directory'; then
    echo "    WARNING: node-exporter is not running with --collector.textfile.directory." >&2
    echo "    Run: cd $REPO/Docker/grafana && docker compose up -d node-exporter" >&2
fi

echo "==> first run (secrets + patches; images are weekly and slow)"
sudo systemctl start security-scan.service
systemctl --no-pager --lines=0 status security-scan.service | head -4 | sed 's/^/    /'

echo
echo "Done. Verify:"
echo "  systemctl list-timers 'security-*'"
echo "  curl -s localhost:9100/metrics | grep '^security_'"
echo "  python3 $HERE/test_security_scan.py"
