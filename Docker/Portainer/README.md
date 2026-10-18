# Portainer

Docker management UI (Portainer CE) for fastpi and, via the Portainer agent, beefy.

- **URL:** https://portainer.holy-grail.ch (LAN/VPN only, Holy Grail SSO login)
- **Login:** native OAuth (Authentik "Holy Grail"). The password login is blocked at
  Traefik (`portainer-password-login-block`, see `../Traefik/traefik/dynamic/portainer.yml`)
  and the HTTPS port is bound to `127.0.0.1:9443`.
- **beefy:** Portainer dials the agent on `beefy:9001` outbound. beefy's firewall
  (`DOCKER-USER` in `/etc/iptables/rules.v4`) only lets fastpi (192.168.1.2) reach 9001.

## Files

| File | Purpose |
|---|---|
| `docker-compose.yaml` | the Portainer container |
| `.env` | admin password, domain, Authentik OAuth client (gitignored) |
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
