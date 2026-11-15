---
title: "Beefy and Tower wakers"
ring: production
quadrant: services
tags: [fastpi, beefy, tower]
---

Small Rust services on fastpi: Traefik asks them before routing to a sleeping host, and they send the wake packet.
The Tower waker has a 34-test black-box suite that was run against both the old Python and the Rust version.
