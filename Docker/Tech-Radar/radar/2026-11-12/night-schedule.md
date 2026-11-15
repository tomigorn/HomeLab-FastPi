---
title: "Night schedule"
ring: production
quadrant: devops
tags: [fastpi, beefy]
---

Every recurring job runs between 22:00 and 06:00 in the low-tariff window, and nothing runs 02:00 to 03:00 so the clock change cannot bite.
One maintenance wake of beefy per night covers its nightly jobs; a second wake at 22:05 happens only when downloads wait for the night.
