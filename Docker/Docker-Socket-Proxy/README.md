# Docker-Socket-Proxy
Proxies in front of `/var/run/docker.sock`; nothing else mounts it. Details: `Docker/_global/docs/container-hardening.md`, section Docker socket.

| Proxy | Network | Allowed |
|---|---|---|
| `socket-proxy-ro` | `socket_proxy` | read-only (containers, images, info, version) |
| `socket-proxy-autoheal` | `socket_proxy_heal` | label-scoped unhealthy list, restart by ID (`autoheal-haproxy.cfg`) |
| `socket-proxy-portupdater` | `socket_proxy_portupdater` | start/stop/restart of 4 named mouse containers (`portupdater-haproxy.cfg`) |

- Bring this project up first: it creates the networks.
- Images pinned by digest (A-30): `SOCKET_PROXY_TAG=v0.5.0@sha256:…` in `.env` (compose default the same), socat `alpine/socat:1.8.1.3@sha256:…`. Update: new digest from `docker buildx imagetools inspect <image:tag>` into `.env`, `.env.example` and the compose default, then `docker compose up -d`. Check `dsp.image-pin`.
- Add a container to the port-updater allow-list: extend the name group in `portupdater-haproxy.cfg`, then `docker compose up -d --force-recreate socket-proxy-portupdater`.
- Test: `docker exec port_updater curl -s -o /dev/null -w '%{http_code}' -X POST http://socket-proxy-portupdater:2375/containers/traefik/restart` must print `403`.
