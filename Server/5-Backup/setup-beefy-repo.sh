#!/usr/bin/env bash
# One-time setup of beefy's backup repo on fastpi: service user, TLS cert, REST login, restic repo with one key for fastpi and one for beefy, credentials copied to beefy. Idempotent, never prints a secret. Run as pi: ./setup-beefy-repo.sh
set -euo pipefail
ETC=/etc/beefy-backup-rest
DATA=/var/lib/beefy-backup
REPO=$DATA/beefy
CONF=/root/.config/restic
BEEFY=${BEEFY:-beefy}
BCONF=/root/.config/restic
export RESTIC_CACHE_DIR=/var/cache/restic

on_beefy_has() { ssh -o BatchMode=yes "$BEEFY" "sudo test -s $BCONF/$1"; }
to_beefy() { ssh -o BatchMode=yes "$BEEFY" "sudo install -d -m 0700 $BCONF && sudo install -D -m 0600 -o root -g root /dev/stdin $BCONF/$1"; }

getent passwd beefy-backup >/dev/null || sudo useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin beefy-backup
sudo install -d -m 0750 -o root -g beefy-backup "$ETC"
sudo install -d -m 0700 -o beefy-backup -g beefy-backup "$DATA"
sudo install -d -m 0700 "$CONF"

if ! sudo test -s "$ETC/tls.crt"; then
    sudo openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 3650 -subj /CN=fastpi-backup \
        -addext subjectAltName=IP:192.168.1.2,DNS:fastpi.homelab -keyout "$ETC/tls.key" -out "$ETC/tls.crt" 2>/dev/null
    sudo chown root:beefy-backup "$ETC/tls.key" "$ETC/tls.crt"; sudo chmod 0640 "$ETC/tls.key"; sudo chmod 0644 "$ETC/tls.crt"
fi
sudo cat "$ETC/tls.crt" | to_beefy fastpi-rest.crt

if ! sudo test -s "$ETC/htpasswd" || ! on_beefy_has fastpi-rest.pass; then
    pw=$(openssl rand -base64 33 | tr -d '\n/+=')
    printf '%s' "$pw" | to_beefy fastpi-rest.pass
    printf '%s\n' "$pw" | sudo htpasswd -iBc "$ETC/htpasswd" beefy 2>/dev/null
    unset pw
    sudo chown root:beefy-backup "$ETC/htpasswd"; sudo chmod 0640 "$ETC/htpasswd"
fi

sudo test -s "$CONF/beefy-repo.pass" || openssl rand -base64 33 | tr -d '\n' | sudo install -m 0600 /dev/stdin "$CONF/beefy-repo.pass"
if ! sudo test -f "$REPO/config"; then
    sudo restic init --repo "$REPO" --password-file "$CONF/beefy-repo.pass" >/dev/null
fi
if ! on_beefy_has beefy.pass; then
    tmp=$(sudo mktemp /root/.beefy-key.XXXXXX)
    openssl rand -base64 33 | tr -d '\n' | sudo tee "$tmp" >/dev/null
    sudo restic key add --repo "$REPO" --password-file "$CONF/beefy-repo.pass" --new-password-file "$tmp" --host beefy --user backup >/dev/null
    sudo cat "$tmp" | to_beefy beefy.pass
    sudo shred -u "$tmp"
fi
sudo chown -R beefy-backup:beefy-backup "$DATA"
sudo restic key list --repo "$REPO" --password-file "$CONF/beefy-repo.pass"
echo "setup done; keep $CONF/beefy-repo.pass in the password manager"
