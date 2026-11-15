---
title: "Portainer"
ring: production
quadrant: devops
tags: [fastpi, beefy]
---

Container management UI for fastpi and, through its agent, beefy.
Read-only on fastpi by design: its socket proxy refuses every change, so it shows stacks and logs only. beefy's agent still has full access.
