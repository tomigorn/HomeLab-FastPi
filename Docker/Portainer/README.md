> Portainer is READ-ONLY since 2026-10-22: its socket proxy denies POST and EXEC,
> so it can view every stack, container and log but cannot start, stop, create or
> exec anything. Manage containers via the shell / compose scripts.

# Portainer

Docker management UI (Portainer CE) for fastpi and, via the Portainer agent, beefy.

- **URL:** https://portainer.holy-grail.ch (LAN/VPN only, Holy Grail SSO login)
- **Login:** native OAuth (Authentik "Holy Grail"). The password login is blocked at
  Traefik (`portainer-password-login-block`, see `../Traefik/traefik/dynamic/portainer.yml`)
  and the HTTPS port is bound to `127.0.0.1:9443`.
- **beefy:** Portainer dials the agent on `beefy:9001` outbound. fastpi's container LAN guard (`_global/scripts/docker-user-lan-guard.sh`) lets only Portainer's pinned `10.24.7.7` (network `traefik_portainer`, shared only with Traefik) reach it; beefy's firewall only accepts 9001 from fastpi (192.168.1.2). Both sides share `AGENT_SECRET` (`.env` here and in beefy's `Docker/Portainer-Agent/.env`).

## Docker socket: through a filtered proxy, not a raw mount

Portainer no longer bind-mounts `/var/run/docker.sock`. It reaches the daemon through
its own `tecnativa/docker-socket-proxy` (`portainer-socket-proxy`) on the internal
`portainer_socket` network. A socat bridge (`portainer-socket-proxy-unix`)
republishes the TCP proxy as a unix socket on the `portainer_sock` volume, mounted at
Portainer's `/var/run`, so Portainer's stored "local" endpoint keeps working unchanged.

| Allowed (read only, `GET`/`HEAD`) | Denied |
|---|---|
| `CONTAINERS` list/inspect/logs/stats | `POST` = every state change: start/stop/restart/create/remove, image pull, exec creation |
| `IMAGES` `NETWORKS` `VOLUMES` list/inspect | `EXEC` (console), `ALLOW_START` `ALLOW_STOP` `ALLOW_RESTARTS` |
| `INFO` `SYSTEM` (`/system/df`) `VERSION` `EVENTS` `PING` | `SECRETS` `CONFIGS` `SWARM` `NODES` `SERVICES` `TASKS` |
| | `PLUGINS` `BUILD` `COMMIT` `AUTH` `SESSION` `DISTRIBUTION` |

**Effect:** with `POST=0` and `EXEC=0` Portainer can view every stack, container and log but cannot change, create or exec anything, so it is not root-equivalent. Manage containers via the shell / compose. The proxy also removes the raw socket-file mount and is one filtered, logged choke point in front of the daemon.

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
