---
title: "healthchecks.io"
ring: production
quadrant: devops
tags: [monitoring, fastpi]
---

External dead-man's switch: Alertmanager pings it every few minutes.
When the pings stop (fastpi down, no internet, monitoring hung) it alerts by Telegram and email from outside.
