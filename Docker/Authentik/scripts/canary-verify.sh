#!/usr/bin/env bash
# Functional SSO verification: enable the canary, do a REAL login+MFA, then ALWAYS
# disable it again (even on failure/timeout). Exit 0 only if the full flow completed.
# This is the check the hardened rules require before trusting an SSO change.
# Optional: canary-verify.sh <app-url> <text> also opens a forward-auth app as the canary (a normal user, no groups) and expects <text> on the page.
set -uo pipefail
PROJ="/home/pi/Projects/Docker/Authentik"

disable() { bash "$PROJ/scripts/canary-disable.sh" >/dev/null 2>&1 || true; echo "canary disabled (cleanup)"; }
trap disable EXIT

bash "$PROJ/scripts/canary-enable.sh" >/dev/null
echo "canary enabled; running real login + MFA ..."
if python3 "$PROJ/scripts/canary_login_test.py" "$@"; then
  echo "SSO_VERIFY_OK: real login + MFA completed end-to-end"
  exit 0
else
  echo "SSO_VERIFY_FAIL: login/MFA or the app check did not complete (see LOGIN_/APP_ lines)"
  exit 1
fi
