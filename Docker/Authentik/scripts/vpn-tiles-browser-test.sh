#!/usr/bin/env bash
# Real logged-in browser check of the VPN hint; the canary is always disabled again. Args go to vpn_tiles_browser_test.cjs (--inject tests the file before it is live).
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
trap 'bash "$HERE/canary-disable.sh" >/dev/null 2>&1; echo "canary disabled (cleanup)"' EXIT
bash "$HERE/canary-enable.sh" >/dev/null
PUBLIC_IP=${PUBLIC_IP:-$(dig +short @1.1.1.1 sso.holy-grail.ch | head -1)} node "$HERE/vpn_tiles_browser_test.cjs" "$@"
