---
title: "Alertmanager and Telegram"
ring: production
quadrant: devops
tags: [monitoring, fastpi]
---

Routes alerts to Telegram (critical ones also by email), muted at night, with a daily and a weekly digest.
An external dead-man's switch (healthchecks.io) fires when the monitoring itself stops.
A direct alert path exists that does not depend on the web edge.
