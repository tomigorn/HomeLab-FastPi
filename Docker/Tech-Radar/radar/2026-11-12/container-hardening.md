---
title: "Container hardening"
ring: production
quadrant: devops
tags: [fastpi, beefy, security]
---

Every container drops all capabilities, sets no-new-privileges and runs under its own non-root uid, with a documented uid map.
Most run with a read-only filesystem and a memory cap.
