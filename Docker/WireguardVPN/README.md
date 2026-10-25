# WireGuard VPN (wg-easy)

WireGuard VPN server managed via wg-easy. The management UI is routed through Traefik and is only accessible from the LAN or while connected via VPN.

- **VPN port:** `51820/udp` — public, reachable via DuckDNS (`hermes-vpn.duckdns.org`)
- **Management UI:** `https://wg-easy.holy-grail.ch` — LAN/VPN only, behind Traefik IPAllowList (`local-networks@file`)
- **What peers reach:** on fastpi only SSH, DNS and the web apps (80/443 via Traefik + SSO) and ping (`_global/scripts/host-input-guard.sh`, `docker-user-lan-guard.sh`); the LAN as before (beefy only 22/8096). Ask the owner before opening more.
- **Login:** Authentik OIDC (application `wg-easy`, group `homelab-admins`); the login page jumps straight to Authentik.
  The Authentik login is linked to the wg-easy `admin` user by its email address (auto-register is off).
  **SSO only:** `DISABLE_PASSWORD_AUTH=true`, so the password login (`/api/auth/password`, `Authorization: Basic`) returns 403.
  Recovery when Authentik is down (server shell only): set `DISABLE_PASSWORD_AUTH=false` in `docker-compose.yaml`,
  `docker compose up -d` (drops VPN tunnels for ~3 s), log in at `https://wg-easy.holy-grail.ch/login?auto_launch=false`,
  then set it back to `true` and `docker compose up -d` again. The admin password is only in wg-easy's database;
  reset it with `docker exec -it WireGuard-VPN cli db:admin:reset`.
  The UI must be opened on exactly this hostname: wg-easy builds the OIDC redirect URI from the Host header.
- **OIDC client secret:** file `secrets/oidc_client_secret` (root, `0400`), exported by the compose entrypoint (wg-easy has no `*_FILE` option), not a compose env value. `provision-admin-sso.py` writes it straight into that file.

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

## VPN clients reaching LAN-only routes (2026-10-19)

VPN clients resolve `*.holy-grail.ch` to 192.168.1.2 via AdGuard. Traffic from inside the
wg-easy container to the host's published ports goes through docker-proxy and arrives at
Traefik as the bridge gateway **172.24.0.1** — the same source as Cloudflare-tunnel internet
traffic, so `local-networks@file` refused it (Forbidden). Fix: the interface **PostUp hook**
(stored in wg-easy's DB, `hooks_table`, Admin → Hooks in the UI) gets one extra rule:

```
iptables -t nat -A PREROUTING -i wg0 -s {{ipv4Cidr}} -d 192.168.1.2 -p tcp -m multiport --dports 80,443 -j DNAT --to-destination 172.24.255.3;
```

(and the matching `-D` in PostDown). Packets then go container-to-container to Traefik
(IP pinned in Docker/Traefik/docker-compose.yaml) and are masqueraded to **172.24.255.5**,
which `local-networks@file` allows. `-i wg0` limits it to real WireGuard clients. If the
wg-easy DB is ever recreated, re-add this hook. Other ports (DNS 53, SSH, AdGuard 3000…) are
unchanged. Backup of the DB before the change: `~/backups/wg-easy.db.bak-2026-10-19`.

The container's **own** requests (e.g. `docker exec WireGuard-VPN …` to 192.168.1.2) are not from `wg0`, so they still hairpin as 172.24.0.1 and get 403 on LAN-only routes: expected, not a client problem. Test the real client path from the container's netns:

```bash
docker run --rm --network container:WireGuard-VPN --user 65026:65026 --cap-drop ALL curlimages/curl:8.23.0 -sk -o /dev/null -w '%{http_code} %{redirect_url}\n' --resolve radarr.holy-grail.ch:443:172.24.255.3 https://radarr.holy-grail.ch/   # 302 -> sso
```
