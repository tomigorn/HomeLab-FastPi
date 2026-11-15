---
title: "mergerfs"
ring: production
quadrant: services
tags: [beefy]
---

Union filesystem on beefy: two 8 TB SSDs as the fast tier in front of a 30 TB HDD.
A nightly mover shifts titles nobody has played for 30 days to the HDD once the SSDs pass 70 %; the HDD spins down when idle.
