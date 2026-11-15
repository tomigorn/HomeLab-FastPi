---
title: "FlareSolverr"
ring: production
quadrant: services
tags: [beefy, media, security]
---

Proxy that gets indexers past browser challenges, inside the VPN container on beefy.
Own image rebuilt weekly with every Debian update, because the upstream one shipped an old Chromium full of CVEs; tests and rollback included.
