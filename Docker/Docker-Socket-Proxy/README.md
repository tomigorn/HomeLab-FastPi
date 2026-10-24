# Docker-Socket-Proxy
Proxies in front of `/var/run/docker.sock`; nothing else mounts it. Details: `Docker/_global/docs/container-hardening.md`, section Docker socket.

| Proxy | Network | Allowed |
|---|---|---|
| `socket-proxy-ro` | `socket_proxy` | read-only (containers, images, info, version) |
| `socket-proxy-autoheal` | `socket_proxy_heal` | label-scoped unhealthy list, restart by ID (`autoheal-haproxy.cfg`) |
| `socket-proxy-portupdater` | `socket_proxy_portupdater` | start/stop/restart of 4 named mouse containers (`portupdater-haproxy.cfg`) |

- Bring this project up first: it creates the networks.
- Add a container to the port-updater allow-list: extend the name group in `portupdater-haproxy.cfg`, then `docker compose up -d --force-recreate socket-proxy-portupdater`.
- Test: `docker exec port_updater curl -s -o /dev/null -w '%{http_code}' -X POST http://socket-proxy-portupdater:2375/containers/traefik/restart` must print `403`.
