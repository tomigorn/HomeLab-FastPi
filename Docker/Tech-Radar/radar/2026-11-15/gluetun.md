---
title: "gluetun and ProtonVPN"
ring: production
quadrant: devops
tags: [fastpi, beefy, network, security]
---

VPN container (ProtonVPN over WireGuard) that the download clients and indexers live inside, on both fastpi and beefy.
Its firewall is the kill switch: tunnel down means no internet for them, never a leak.
On fastpi a small Rust helper keeps qBittorrent's port on the forwarded VPN port.
