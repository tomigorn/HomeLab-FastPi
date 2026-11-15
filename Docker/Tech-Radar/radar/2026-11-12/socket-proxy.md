---
title: "Docker socket proxies"
ring: production
quadrant: devops
tags: [fastpi, security]
---

No container on fastpi mounts the Docker socket directly, only the proxies; each consumer gets one that allows only what it needs.
Portainer is read-only: it can view everything and start nothing.
