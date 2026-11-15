---
title: "WireGuard"
ring: production
quadrant: services
tags: [network, fastpi, security]
---

VPN server (wg-easy) on a public UDP port; its admin UI logs in through Authentik only.
Peers reach the LAN, but on fastpi only SSH, DNS and the web apps, and on beefy only SSH and Jellyfin; admin UIs stay behind the single login.
