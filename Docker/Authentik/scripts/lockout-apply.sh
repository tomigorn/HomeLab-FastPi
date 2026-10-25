#!/usr/bin/env bash
# Verified apply of the brute-force lockout: bind (negate) -> functionally verify a
# real login+MFA still works via the canary -> keep it; on any verify failure, roll
# back immediately and page out-of-band. This is the safe, unattended-capable path.
set -uo pipefail
SCR="/home/pi/Projects/Docker/Authentik/scripts"
OOB="/home/pi/Projects/Docker/_global/scripts/oob-alert.sh"

echo "1/3 applying lockout binding (negate on) ..."
bash "$SCR/lockout-bind.sh" apply || { echo "APPLY_FAILED (bind error)"; exit 1; }

echo "2/3 verifying a real login + MFA still works ..."
if bash "$SCR/canary-verify.sh"; then
  echo "3/3 LOCKOUT_APPLIED_AND_VERIFIED: binding active AND legitimate login+MFA confirmed working."
  bash "$SCR/lockout-bind.sh" status
  exit 0
else
  echo "VERIFY FAILED — legitimate login broke. Rolling back immediately ..."
  bash "$SCR/lockout-bind.sh" rollback
  bash "$OOB" $'🟠 <b>Authentik lockout apply failed</b>\n\n• Verification failed: login broke\n• Rolled back automatically, SSO should be back to normal\n• Please check' || true
  echo "ROLLED_BACK and paged. Lockout NOT active."
  exit 1
fi
