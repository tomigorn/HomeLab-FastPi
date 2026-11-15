---
title: "Private-tracker seedbox"
ring: production
quadrant: services
tags: [fastpi, media]
---

Always-on qBittorrent behind the VPN on fastpi that seeds audiobooks from a private tracker indefinitely.
A helper (Mousehole) keeps the tracker session valid when the VPN address changes; it feeds the audiobook pipeline and stays on fastpi so beefy can sleep.
