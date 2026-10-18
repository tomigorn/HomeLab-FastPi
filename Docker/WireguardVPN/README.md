# WireGuard VPN (wg-easy)

WireGuard VPN server managed via wg-easy. The management UI is routed through Traefik and is only accessible from the LAN or while connected via VPN.

- **VPN port:** `51820/udp` — public, reachable via DuckDNS (`hermes-vpn.duckdns.org`)
- **Management UI:** `https://wg-easy.holy-grail.ch` — LAN/VPN only, behind Traefik IPAllowList (`local-networks@file`)
- **Login:** Authentik OIDC (application `wg-easy`, group `homelab-admins`); the login page jumps straight to Authentik.
  The Authentik login is linked to the wg-easy `admin` user by its email address (auto-register is off).
  **SSO only:** `DISABLE_PASSWORD_AUTH=true`, so the password login (`/api/auth/password`, `Authorization: Basic`) returns 403.
  Recovery when Authentik is down (server shell only): set `DISABLE_PASSWORD_AUTH=false` in `docker-compose.yaml`,
  `docker compose up -d` (drops VPN tunnels for ~3 s), log in at `https://wg-easy.holy-grail.ch/login?auto_launch=false`,
  then set it back to `true` and `docker compose up -d` again. The admin password is only in wg-easy's database;
  reset it with `docker exec -it WireGuard-VPN cli db:admin:reset`.
  The UI must be opened on exactly this hostname: wg-easy builds the OIDC redirect URI from the Host header.

---

## Break-glass: SSH via Cloudflare

If the management UI is unreachable (e.g. AdGuard DNS is down, Traefik is down, or you are locked out remotely), access the Pi directly via the Cloudflare SSH tunnel. This path is independent of local DNS and Traefik.

**Requirements:**
- `cloudflared` installed on your local machine
- Your email address whitelisted in the Cloudflare Access policy
- Your SSH private key available locally

### Connect

```bash
ssh -o ProxyCommand='cloudflared access ssh --hostname terminal.holy-grail.ch' pi@terminal.holy-grail.ch
```

Your browser will open automatically for Cloudflare Access authentication — enter the one-time code sent to your whitelisted email. Once approved, the SSH session opens.

### Shorthand (add to `~/.ssh/config`)

```
Host terminal.holy-grail.ch
  ProxyCommand cloudflared access ssh --hostname %h
  User pi
```

Then connect with just:

```bash
ssh terminal.holy-grail.ch
```

### Security layers on this path

1. **Cloudflare Access** — email OTP required, sender must be whitelisted
2. **SSH** — password authentication disabled, key-only

### Common recovery commands

```bash
# Restart AdGuard (fixes DNS issues)
cd ~/Projects/Docker/adguard && docker compose restart

# Restart Traefik (fixes routing issues)
cd ~/Projects/Docker/Traefik && docker compose restart

# Restart WireGuard
cd ~/Projects/Docker/WireguardVPN && docker compose restart

# Check container status
docker ps
```
