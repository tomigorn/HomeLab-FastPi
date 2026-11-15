---
title: "Security monitoring"
ring: production
quadrant: devops
tags: [security, monitoring, fastpi, beefy, tower]
---

Scheduled checks on all three hosts: leaked secrets, OS patches, malware, rootkits, container CVEs, SSH logins and config changes.
Every finding becomes a metric; urgent ones alert by Telegram at once, the rest go into the daily digest.
A weekly digest sums up updates and CVEs; sleeping hosts are never woken for it.
