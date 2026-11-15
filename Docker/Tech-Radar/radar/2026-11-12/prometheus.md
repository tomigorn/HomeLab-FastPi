---
title: "Prometheus"
ring: production
quadrant: devops
tags: [monitoring, fastpi]
---

Metrics store on fastpi: scrapes fastpi's exporters and the edge services, and probes the public routes, beefy and tower.
beefy's own metrics and the security checks arrive as files, so sleeping hosts are never woken for a scrape.
