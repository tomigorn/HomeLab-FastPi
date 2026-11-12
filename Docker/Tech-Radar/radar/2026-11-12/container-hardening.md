---
title: "Container hardening"
ring: production
quadrant: devops
tags: [fastpi, beefy, security]
---

Every container drops all capabilities and sets no-new-privileges; all but a few documented exceptions run under their own non-root uid, with a documented uid map.
Most run with a read-only filesystem and a memory cap.
