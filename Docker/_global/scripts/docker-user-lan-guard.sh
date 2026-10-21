#!/usr/bin/env bash
# docker-user-lan-guard.sh — stop bridged containers from reaching the LAN.
#
# Containers must still reach the internet, the host's own published ports
# (those hit INPUT, not FORWARD, so they are never matched here) and the two
# two trusted homelab servers — and only the containers that legitimately need
# them (Traefik, the grafana stack) are let through, by source. Everything else
# on 192.168.1.0/24 — the router, IoT plugs, any other device, and any other
# container — is blocked. Host-network services (Home Assistant, the wakers)
# are unaffected because their traffic is host traffic, not forwarded.
#
# Idempotent: rebuilds the DOCKER-USER chain from scratch on every run.
# Persist with `netfilter-persistent save` after running.
set -euo pipefail

IFACE=eth0
LAN=192.168.1.0/24
TOWER=192.168.1.101       # tower (Unraid NAS)
BEEFY=192.168.1.102       # beefy (media server)
VPN_NAT=172.24.255.5/32   # wg-easy SNAT source — VPN clients keep LAN reach
TRAEFIK=172.24.255.3/32   # Traefik (pinned) — proxies the media + nextcloud routes
MONITORING=192.168.208.0/20  # grafana stack — blackbox probes beefy/tower :22/:8080

iptables -N DOCKER-USER 2>/dev/null || true
iptables -C FORWARD -j DOCKER-USER 2>/dev/null || iptables -I FORWARD -j DOCKER-USER

iptables -F DOCKER-USER
iptables -A DOCKER-USER -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -A DOCKER-USER -s "$VPN_NAT" -o "$IFACE" -j RETURN
iptables -A DOCKER-USER -s "$TRAEFIK" -o "$IFACE" -d "$TOWER" -j RETURN
iptables -A DOCKER-USER -s "$TRAEFIK" -o "$IFACE" -d "$BEEFY" -j RETURN
iptables -A DOCKER-USER -s "$MONITORING" -o "$IFACE" -d "$TOWER" -j RETURN
iptables -A DOCKER-USER -s "$MONITORING" -o "$IFACE" -d "$BEEFY" -j RETURN
iptables -A DOCKER-USER -o "$IFACE" -d "$LAN" -j DROP
iptables -A DOCKER-USER -j RETURN

echo "DOCKER-USER rules applied:"
iptables -L DOCKER-USER -n -v --line-numbers
