#!/usr/bin/env bash
# docker-user-lan-guard.sh — stop bridged containers from reaching the LAN.
#
# Containers must still reach the internet, the host's own published ports (those hit INPUT, not FORWARD, so they are never matched here) and the two trusted homelab servers, but only the containers that need them, by source and port:
#   Traefik → beefy/tower (all ports: it proxies them), grafana stack → beefy :22, tower :22/:8080 (blackbox), m4b → beefy :22, Cup → beefy :8000, Portainer → beefy :9001.
#   VPN clients (wg-easy NAT) → no host-published port reached by DNAT (m4b :8099, Cup :8000; only SSH/DNS/web on the host, see host-input-guard.sh) → whole LAN, but on beefy only :22 (ssh), :8096 (Jellyfin apps) and ping: beefy's admin backends trust 192.168.1.2 and have no login of their own, so they stay behind Traefik + Authentik.
# Everything else on 192.168.1.0/24 (router, IoT plugs, any other device, any other container) is blocked. Host-network services (Home Assistant, the wakers) are host traffic, not forwarded: host-output-guard.sh limits that towards beefy.
#
# Idempotent: rebuilds the DOCKER-USER chain from scratch on every run.
# Persist: `docker-user-lan-guard.sh --persist` (calls iptables-persist.sh) writes /etc/iptables/rules.v4/v6 with ONLY our own chains (DOCKER-USER, HOST-GUARD). Never `netfilter-persistent save`: it freezes Docker's own per-bridge rules, which come back at boot for bridges that no longer exist and silently drop traffic to reused container IPs (Cup → its agent, 2026-10-24).
set -euo pipefail

IFACE=eth0
LAN=192.168.1.0/24
TOWER=192.168.1.101       # tower (Unraid NAS)
BEEFY=192.168.1.102       # beefy (media server)
VPN_NAT=172.24.255.5/32   # wg-easy SNAT source — VPN clients keep LAN reach, but on beefy only ssh + Jellyfin (admin UIs go through Traefik + Authentik)
TRAEFIK=172.24.255.3/32   # Traefik (pinned) — proxies the media + nextcloud routes
MONITORING=192.168.208.0/20  # grafana stack — blackbox probes beefy :22, tower :22/:8080
M4B=192.168.64.0/20       # m4b-auto-merge — ssh to beefy, which transcodes
CUP=172.31.0.0/16         # Cup server (cup_cup_agents) — reads the beefy agent
PORTAINER=172.24.255.7/32 # Portainer (pinned) — manages beefy through its agent

iptables -N DOCKER-USER 2>/dev/null || true
iptables -C FORWARD -j DOCKER-USER 2>/dev/null || iptables -I FORWARD -j DOCKER-USER

iptables -F DOCKER-USER
iptables -A DOCKER-USER -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -A DOCKER-USER -s "$VPN_NAT" -m conntrack --ctstate DNAT -j DROP
iptables -A DOCKER-USER -s "$VPN_NAT" -o "$IFACE" -d "$BEEFY" -p tcp -m multiport --dports 22,8096 -j RETURN
iptables -A DOCKER-USER -s "$VPN_NAT" -o "$IFACE" -d "$BEEFY" -p icmp -j RETURN
iptables -A DOCKER-USER -s "$VPN_NAT" -o "$IFACE" -d "$BEEFY" -j DROP
iptables -A DOCKER-USER -s "$VPN_NAT" -o "$IFACE" -j RETURN
iptables -A DOCKER-USER -s "$TRAEFIK" -o "$IFACE" -d "$TOWER" -j RETURN
iptables -A DOCKER-USER -s "$TRAEFIK" -o "$IFACE" -d "$BEEFY" -j RETURN
iptables -A DOCKER-USER -s "$MONITORING" -o "$IFACE" -d "$TOWER" -p tcp -m multiport --dports 22,8080 -j RETURN
iptables -A DOCKER-USER -s "$MONITORING" -o "$IFACE" -d "$BEEFY" -p tcp --dport 22 -j RETURN
iptables -A DOCKER-USER -s "$M4B" -o "$IFACE" -d "$BEEFY" -p tcp --dport 22 -j RETURN
iptables -A DOCKER-USER -s "$CUP" -o "$IFACE" -d "$BEEFY" -p tcp --dport 8000 -j RETURN
iptables -A DOCKER-USER -s "$PORTAINER" -o "$IFACE" -d "$BEEFY" -p tcp --dport 9001 -j RETURN
iptables -A DOCKER-USER -o "$IFACE" -d "$LAN" -j DROP
iptables -A DOCKER-USER -j RETURN

echo "DOCKER-USER rules applied:"
iptables -L DOCKER-USER -n -v --line-numbers

if [ "${1:-}" = --persist ]; then
  "$(dirname "$0")/iptables-persist.sh"
fi
