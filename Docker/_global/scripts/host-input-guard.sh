#!/usr/bin/env bash
# host-input-guard.sh — limit what containers and VPN peers may reach on the host itself.
#
# Traffic that enters from a Docker bridge (docker0, br-*) and is addressed to the host hits INPUT: DNS to AdGuard, Traefik → host-network services, docker-proxy hairpins (VPN peers → 192.168.1.2:443), cloudflared → sshd. Without this guard every container and VPN peer reaches every host listener (sshd, samba, AdGuard admin, HA, go2rtc, wakers).
# Only the flows below are allowed from bridges, by source and port; everything else from a bridge is dropped. LAN (eth0) and loopback are not matched; OUTPUT to beefy is host-output-guard.sh.
# IPv6: no Docker network has IPv6; bridges get established + ICMPv6 only, eth0 accepts NEW only from link-local/ULA (no exposure if the ISP ever enables global IPv6).
#
# Idempotent: rebuilds HOST-GUARD / HOST-GUARD6 and their INPUT hooks on every run. The hooks never reference Docker's chains, so rules.v4/v6 restore at boot before Docker starts.
# Persist: `host-input-guard.sh --persist` (calls iptables-persist.sh: rules.v4/v6 get only our own chains). Never `netfilter-persistent save`.
set -euo pipefail

TRAEFIK=172.24.255.3/32     # Traefik (pinned) — proxies the host-network services
VPN_NAT=172.24.255.5/32     # wg-easy SNAT source — the owner's remote devices
CLOUDFLARED=172.20.0.0/16   # infra__cloudflare_default — tunnel route terminal.holy-grail.ch → ssh://192.168.1.2:22

DNS=53
TRAEFIK_EP=80,443,8080,8443                     # Traefik's published entrypoints (docker-proxy hairpin from traefik_proxy)
TRAEFIK_BACKENDS=3000,8123,9001,9002            # AdGuard admin, Home Assistant, beefy/tower wakers (host network)
VPN_TCP=22,139,445,8099,8123,18555              # ssh, samba, m4b dashboard, HA app, go2rtc WebRTC
VPN_UDP=18555

v4() {
  iptables -N HOST-GUARD 2>/dev/null || true
  iptables -F HOST-GUARD
  iptables -A HOST-GUARD -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
  iptables -A HOST-GUARD -p icmp -j RETURN
  iptables -A HOST-GUARD -p udp --dport $DNS -j RETURN
  iptables -A HOST-GUARD -p tcp --dport $DNS -j RETURN
  iptables -A HOST-GUARD -p tcp -m multiport --dports $TRAEFIK_EP -j RETURN
  iptables -A HOST-GUARD -s "$TRAEFIK" -p tcp -m multiport --dports $TRAEFIK_BACKENDS -j RETURN
  iptables -A HOST-GUARD -s "$CLOUDFLARED" -p tcp --dport 22 -j RETURN
  iptables -A HOST-GUARD -s "$VPN_NAT" -p tcp -m multiport --dports $VPN_TCP -j RETURN
  iptables -A HOST-GUARD -s "$VPN_NAT" -p udp -m multiport --dports $VPN_UDP -j RETURN
  iptables -A HOST-GUARD -m limit --limit 6/min --limit-burst 20 -j LOG --log-prefix "host-guard drop: " --log-level 6
  iptables -A HOST-GUARD -j DROP
  for i in docker0 br-+; do
    iptables -C INPUT -i "$i" -j HOST-GUARD 2>/dev/null || iptables -I INPUT -i "$i" -j HOST-GUARD
  done
}

v6() {
  ip6tables -N HOST-GUARD6 2>/dev/null || true
  ip6tables -F HOST-GUARD6
  ip6tables -A HOST-GUARD6 -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
  ip6tables -A HOST-GUARD6 -p ipv6-icmp -j RETURN
  ip6tables -A HOST-GUARD6 -i eth0 -s fe80::/10 -j RETURN
  ip6tables -A HOST-GUARD6 -i eth0 -s fc00::/7 -j RETURN
  ip6tables -A HOST-GUARD6 -i eth0 -d ff00::/8 -j RETURN
  ip6tables -A HOST-GUARD6 -m limit --limit 6/min --limit-burst 20 -j LOG --log-prefix "host-guard6 drop: " --log-level 6
  ip6tables -A HOST-GUARD6 -j DROP
  for i in docker0 br-+ eth0; do
    ip6tables -C INPUT -i "$i" -j HOST-GUARD6 2>/dev/null || ip6tables -I INPUT -i "$i" -j HOST-GUARD6
  done
}

v4
v6
echo "HOST-GUARD rules applied:"
iptables -L HOST-GUARD -n -v --line-numbers
ip6tables -L HOST-GUARD6 -n -v --line-numbers

if [ "${1:-}" = --persist ]; then
  "$(dirname "$0")/iptables-persist.sh"
fi
