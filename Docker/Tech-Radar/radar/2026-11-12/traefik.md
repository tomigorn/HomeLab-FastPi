---
title: "Traefik"
ring: production
quadrant: services
tags: [fastpi, network, security]
---

The reverse proxy in front of every web service, with two local plugins (real client IP and the CrowdSec bouncer) instead of registry downloads.
Unauthenticated requests are redirected to the login; admin tools are reachable from the LAN or VPN only.
