#!/usr/bin/env bash
# Units that handle untrusted input (downloads, MAM/Seerr/beefy data, scan results) keep the sandbox baseline (D-01). Usage: scripts/test_unit_sandbox.sh
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }
UNITS=(
  Docker/antivirus/systemd/clamav-scan.service Docker/antivirus/systemd/clamav-hostscan.service
  Docker/_global/systemd/mam-points.service Docker/_global/systemd/subscription-alerts.service
  Server/4-Security-Monitoring/security-scan.service Server/4-Security-Monitoring/security-image-scan.service
  Server/4-Security-Monitoring/security-av.service Server/4-Security-Monitoring/security-av-hits.service
  Server/4-Security-Monitoring/security-code-scan.service Server/4-Security-Monitoring/security-dt.service
  Server/4-Security-Monitoring/beefy-idle-pull.service
)
NEED=(NoNewPrivileges=true ProtectSystem=strict ProtectHome=read-only PrivateTmp=true PrivateDevices=true
  ProtectKernelTunables=true ProtectKernelModules=true ProtectKernelLogs=true ProtectControlGroups=true
  ProtectClock=true ProtectHostname=true RestrictSUIDSGID=true RestrictRealtime=true RestrictNamespaces=true
  LockPersonality=true SystemCallArchitectures=native CapabilityBoundingSet= 'RestrictAddressFamilies=AF_UNIX')
for u in "${UNITS[@]}"; do
  f="$REPO/$u"; [[ -f $f ]] || { bad "$u" missing; continue; }
  miss=(); for n in "${NEED[@]}"; do grep -q "^$n" "$f" || miss+=("$n"); done
  (( ${#miss[@]} == 0 )) && ok "$u sandboxed" || bad "$u" "missing ${miss[*]}"
  grep -E '^Exec' "$f" | grep -qw sudo && bad "$u calls sudo (NoNewPrivileges breaks it)" || ok "$u no sudo"
done
echo "unit-sandbox: $PASS passed, $FAIL failed"; (( FAIL == 0 ))
