---
title: "Linux and systemd timers"
ring: production
quadrant: devops
tags: [fastpi, beefy]
---

fastpi runs Debian 13 (upgraded in place on 2026-10-25), beefy Ubuntu 26.04; both install security updates by themselves and never reboot on their own.
Every scheduled job is a systemd timer, placed in the night window.
