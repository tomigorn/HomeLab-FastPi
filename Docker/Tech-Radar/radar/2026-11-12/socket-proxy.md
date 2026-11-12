---
title: "Docker socket proxies"
ring: production
quadrant: devops
tags: [fastpi, security]
---

No container mounts the Docker socket directly; each consumer gets a proxy that allows only what it needs.
Portainer is read-only: it can view everything and start nothing.
