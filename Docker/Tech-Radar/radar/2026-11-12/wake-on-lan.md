---
title: "Wake-on-LAN"
ring: production
quadrant: devops
tags: [fastpi, beefy, tower, network]
---

beefy and tower power off when idle (beefy after 15 min, tower after 30 min); fastpi sends a magic packet when a request arrives.
A wait page shows how long the wake has taken; for beefy, a failed signed-in wake triggers a power-cycle and an alert.
The load split: fastpi is always on, the heavy storage and media hosts only run when used.
