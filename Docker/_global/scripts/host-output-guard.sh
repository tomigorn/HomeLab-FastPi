#!/usr/bin/env bash
# host-output-guard.sh — limit what fastpi itself may open on beefy.
#
# beefy's admin apps (arr, Bazarr, qBittorrent) trust any connection from 192.168.1.2 and have no login of their own (review B-01). Bridged containers are already limited by DOCKER-USER (only Traefik reaches the app ports), but traffic that starts on the host (host processes and host-network containers: Home Assistant, AdGuard, samba, duckdns, noip, the wakers) leaves via OUTPUT and is not forwarded.
# From the host to beefy only: ssh (scripts, security scans, smoke test, Server-Specs), ping (maintenance wake), and the Beefy-Waker (uid 65005), whose Traefik gate probes the routed app ports and Jellyfin's /health. Everything else is dropped + logged (`host-out-guard drop:`). Traefik → beefy is forwarded, not OUTPUT, so it is not matched.
# IPv6: beefy has only link-local addresses and its BEEFY-INPUT6 drops new TCP except 22, so no v6 chain here.
#
# Idempotent: rebuilds HOST-OUT-GUARD and its OUTPUT hook on every run.
# Persist: `host-output-guard.sh --persist` (calls iptables-persist.sh). Never `netfilter-persistent save`.
set -euo pipefail

BEEFY=192.168.1.102/32
WAKER_UID=65005   # Beefy-Waker (host network), see docs/container-hardening.md

iptables -N HOST-OUT-GUARD 2>/dev/null || true
iptables -F HOST-OUT-GUARD
iptables -A HOST-OUT-GUARD -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -A HOST-OUT-GUARD -p icmp -j RETURN
iptables -A HOST-OUT-GUARD -p tcp --dport 22 -j RETURN
iptables -A HOST-OUT-GUARD -p tcp -m owner --uid-owner $WAKER_UID -j RETURN
iptables -A HOST-OUT-GUARD -m limit --limit 6/min --limit-burst 20 -j LOG --log-prefix "host-out-guard drop: " --log-level 6 --log-uid
iptables -A HOST-OUT-GUARD -j DROP
iptables -C OUTPUT -d "$BEEFY" -j HOST-OUT-GUARD 2>/dev/null || iptables -I OUTPUT -d "$BEEFY" -j HOST-OUT-GUARD

echo "HOST-OUT-GUARD rules applied:"
iptables -L HOST-OUT-GUARD -n -v --line-numbers

if [ "${1:-}" = --persist ]; then
  "$(dirname "$0")/iptables-persist.sh"
fi
