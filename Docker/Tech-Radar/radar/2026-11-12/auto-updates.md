---
title: "Auto-updates with rollback"
ring: production
quadrant: devops
tags: [fastpi, beefy, security]
---

Tiered nightly image updates: stateless projects update themselves after a 24 h cool-down, run a post-update check and roll back if a customization is gone or broken.
The edge and stateful projects only get a notice with the exact command; locally built images are rebuilt weekly on a fresh base, with tests and rollback.
