# WireGuard VPN (wg-easy)

WireGuard VPN server managed via wg-easy. The management UI is routed through Traefik and is only accessible from the LAN or while connected via VPN.

- **VPN port:** `51820/udp` — public, reachable via DuckDNS (`hermes-vpn.duckdns.org`)
- **Management UI:** `http://wg-easy.fastpi.homelab:8080` — LAN/VPN only, behind Traefik IPAllowList

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
