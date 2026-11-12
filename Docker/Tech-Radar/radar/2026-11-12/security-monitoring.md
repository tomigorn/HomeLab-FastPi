---
title: "Security monitoring"
ring: production
quadrant: devops
tags: [security, monitoring, fastpi, beefy, tower]
---

Scheduled checks on all three hosts: leaked secrets, OS patches, malware, rootkits, container CVEs, SSH logins and config changes.
Every finding becomes a metric and a Telegram alert.
A weekly digest sums it up; sleeping hosts are never woken for it.
