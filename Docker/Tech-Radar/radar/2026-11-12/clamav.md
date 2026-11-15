---
title: "ClamAV"
ring: production
quadrant: devops
tags: [security, fastpi, beefy, tower]
---

Daily scans of new files on all three hosts, plus a weekly whole-host pass over about 289,000 files on fastpi.
Downloads on beefy are scanned by a hook and quarantined before they reach the library; VirusTotal gives a second opinion by hand.
