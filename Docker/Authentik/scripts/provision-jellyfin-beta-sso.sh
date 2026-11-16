#!/usr/bin/env bash
# Runs provision-jellyfin-beta-sso.py and hands the client id/secret straight to beefy (Jellyfin-Beta/secrets/oidc.json, 600), never to the terminal. Then re-run the beta's sanitize.py and restart it (printed hint).
# Usage: provision-jellyfin-beta-sso.sh [--rollback]
set -euo pipefail
cd /home/pi/Projects/Docker/Authentik
case "${1:-}" in
  "") rb=0 ;;
  --rollback) rb=1 ;;
  -h|--help) sed -n 2,3p "$0"; exit 0 ;;
  *) echo "usage: $0 [--rollback]" >&2; exit 2 ;;
esac
out=$(sudo docker compose exec -T -e ROLLBACK=$rb server ak shell < scripts/provision-jellyfin-beta-sso.py 2>/dev/null)
grep '^OK ' <<<"$out" || { echo "provisioning failed (no OK line)" >&2; exit 1; }
if [ "$rb" = 1 ]; then
  ssh beefy-direct 'rm -f ~/Projects/Docker/Jellyfin-Beta/secrets/oidc.json'
  echo "next: ssh beefy-direct 'cd ~/Projects/Docker/Jellyfin-Beta && sudo docker compose stop && sudo python3 scripts/sanitize.py && sudo docker compose start'"
  exit 0
fi
grep '^OIDC_JSON ' <<<"$out" | sed 's/^OIDC_JSON //' | ssh beefy-direct 'umask 077; cat > ~/Projects/Docker/Jellyfin-Beta/secrets/oidc.json && echo "oidc.json written ($(wc -c < ~/Projects/Docker/Jellyfin-Beta/secrets/oidc.json) bytes)"'
echo "next: ssh beefy-direct 'cd ~/Projects/Docker/Jellyfin-Beta && sudo docker compose stop && sudo python3 scripts/sanitize.py && sudo docker compose start', then bash scripts/canary-verify.sh"
