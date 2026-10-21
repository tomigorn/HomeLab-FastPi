> Portainer is READ-ONLY since 2026-10-22: its socket proxy denies POST and EXEC,
> so it can view every stack, container and log but cannot start, stop, create or
> exec anything. Manage containers via the shell / compose scripts.

# Portainer

Docker management UI (Portainer CE) for fastpi and, via the Portainer agent, beefy.

- **URL:** https://portainer.holy-grail.ch (LAN/VPN only, Holy Grail SSO login)
- **Login:** native OAuth (Authentik "Holy Grail"). The password login is blocked at
  Traefik (`portainer-password-login-block`, see `../Traefik/traefik/dynamic/portainer.yml`)
  and the HTTPS port is bound to `127.0.0.1:9443`.
- **beefy:** Portainer dials the agent on `beefy:9001` outbound. beefy's firewall
  (`DOCKER-USER` in `/etc/iptables/rules.v4`) only lets fastpi (192.168.1.2) reach 9001.

## Docker socket: through a filtered proxy, not a raw mount

Portainer no longer bind-mounts `/var/run/docker.sock`. It reaches the daemon through
its own `tecnativa/docker-socket-proxy` (`portainer-socket-proxy`) on the internal
`portainer_socket` network. A socat bridge (`portainer-socket-proxy-unix`)
republishes the TCP proxy as a unix socket on the `portainer_sock` volume, mounted at
Portainer's `/var/run`, so Portainer's stored "local" endpoint keeps working unchanged.

| Allowed (groups Portainer uses) | Denied (everything else) |
|---|---|
| `CONTAINERS` list/inspect/logs/start/stop/restart/create/remove | `SECRETS` `CONFIGS` |
| `IMAGES` list + pull | `SWARM` `NODES` `SERVICES` `TASKS` |
| `NETWORKS`, `VOLUMES` | `PLUGINS` `BUILD` `COMMIT` |
| `INFO` `SYSTEM` (`/system/df`) `VERSION` `EVENTS` `PING` | `AUTH` `SESSION` `DISTRIBUTION` |
| `POST` (state changes + exec creation), `EXEC` (console) | |

**Honest limit:** this does NOT make Portainer non-root-equivalent. Portainer creates
containers, and container-create with bind mounts is itself root on the host, so the
`CONTAINERS`+`POST` grant is inherently privileged. What the proxy removes is the raw
socket-file mount; it blocks the dangerous groups Portainer never needs (swarm,
secrets, configs, nodes, services, tasks, plugins, build), and it gives one filtered,
logged, restartable choke point in front of the daemon instead of a direct mount.
Verify the raw mount is gone: `docker inspect portainer` shows no `/var/run/docker.sock`
bind — only the `portainer_sock` volume at `/var/run`.

## Files

| File | Purpose |
|---|---|
| `docker-compose.yaml` | Portainer + its socket proxy + socat unix bridge |
| `.env` | admin password, domain, Authentik OAuth client, proxy image/tag (gitignored) |
| `.env.example` | same, with secrets blanked |
| `backup/` | Portainer backups (gitignored) |

`COMPOSE_PROJECT_NAME` is `docker` for historical reasons and must NOT be renamed:
the data volume is `docker_portainer_data`, and a new project name would orphan it.

## Deploy

```bash
cd /home/pi/Projects/Docker/Portainer && docker compose up -d
```

## Recovery (Authentik down, server shell only)

- `ssh -L 9443:127.0.0.1:9443 fastpi`, then `https://localhost:9443/#!/internal-auth`
  as the initial admin (`PORTAINER_ADMIN_PASSWORD` in `.env`).
- Lost password: stop the container, then
  `docker run --rm -v docker_portainer_data:/data portainer/helper-reset-password`.
