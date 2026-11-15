---
title: "Container hardening"
ring: production
quadrant: devops
tags: [fastpi, beefy, security]
---

Every container except a parked project drops all capabilities (adding back only what it needs) and sets no-new-privileges; all but a few documented exceptions run under their own non-root uid, with a documented uid map.
Every container has a memory cap; many also run with a read-only filesystem.
