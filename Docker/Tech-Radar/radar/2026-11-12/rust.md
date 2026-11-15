---
title: "Rust"
ring: production
quadrant: languages
tags: [dev, fastpi]
---

Used for the small always-on services: the Beefy and Tower wakers, Activity, Stonks, the audiobook importer and several helpers, most rewritten from Python in November 2026.
Most are static binaries in `scratch` images with no shell and no OS; Stonks is a 16 MB image using a few MB of RAM.
