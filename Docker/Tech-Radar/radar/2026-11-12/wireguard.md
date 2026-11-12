---
title: "WireGuard"
ring: production
quadrant: services
tags: [network, fastpi, security]
---

VPN server (wg-easy) on a public UDP port with login through Authentik.
Peers reach only SSH, DNS and the web apps, not the whole LAN.
