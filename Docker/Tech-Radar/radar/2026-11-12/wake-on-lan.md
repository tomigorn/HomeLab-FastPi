---
title: "Wake-on-LAN"
ring: production
quadrant: devops
tags: [fastpi, beefy, tower, network]
---

beefy and tower power off when idle (beefy after 15 min, tower after 30 min); fastpi sends a magic packet when a request arrives.
A wake page shows a countdown; a failed wake triggers a power-cycle and an alert.
The load split: fastpi is always on, the heavy storage and media hosts only run when used.
