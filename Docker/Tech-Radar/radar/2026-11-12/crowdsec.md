---
title: "CrowdSec"
ring: production
quadrant: services
tags: [security, fastpi, network]
---

Reads Traefik's access log, bans attackers and enforces the bans on every public route.
Also uses the community blocklist of about 18,000 IPs, refreshed every 2 h.
If it is down the edge keeps the last ban list rather than blocking everyone.
