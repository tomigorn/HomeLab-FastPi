#!/usr/bin/env bash
# iptables-persist.sh — write /etc/iptables/rules.v4/v6 with ONLY our own chains (DOCKER-USER, HOST-GUARD, HOST-GUARD6) and their hooks, from the live rules.
# Called by the --persist of docker-user-lan-guard.sh, host-input-guard.sh and host-output-guard.sh. Never `netfilter-persistent save`: it freezes Docker's per-bridge rules, which come back at boot for bridges that no longer exist (Cup → agent broke 2026-10-24).
# Each file is tested with --test and must restore into an empty netns before it replaces the old one.
set -euo pipefail

chain() { # tool chain hook-chain: the :chain line, the hooks into it, its rules
  local tool=$1 c=$2 hook=$3
  $tool -S "$c" >/dev/null 2>&1 || return 0
  echo ":$c - [0:0]"
  $tool -S "$hook" | grep -E -- "-j $c\$" || true
  $tool -S "$c" | grep '^-A '
}

write() { # tool out chains...
  local tool=$1 out=$2; shift 2
  local tmp; tmp=$(mktemp)
  { echo "# Written by _global/scripts/iptables-persist.sh: only our own chains, Docker builds its own."
    echo "*filter"
    for c in "$@"; do
      case $c in DOCKER-USER) chain "$tool" "$c" FORWARD ;; HOST-OUT-GUARD) chain "$tool" "$c" OUTPUT ;; *) chain "$tool" "$c" INPUT ;; esac
    done
    echo "COMMIT"; } > "$tmp"
  "$tool-restore" --test < "$tmp"
  local ns=persist-test-$$
  ip netns add "$ns"
  if ! ip netns exec "$ns" "$tool-restore" < "$tmp"; then ip netns del "$ns"; rm -f "$tmp"; echo "restore into empty netns failed: $out" >&2; exit 1; fi
  ip netns del "$ns"
  [ -e "$out" ] && cp -a "$out" "$out.bak-$(date +%Y%m%d-%H%M%S)"
  install -m 640 "$tmp" "$out"
  rm -f "$tmp"
  echo "persisted to $out"
}

write iptables /etc/iptables/rules.v4 DOCKER-USER HOST-GUARD HOST-OUT-GUARD
write ip6tables /etc/iptables/rules.v6 HOST-GUARD6
