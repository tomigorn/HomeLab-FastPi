Create the shared proxy network before starting any services.
The subnet must be pinned so the gateway IP (`172.24.0.1`) is always
predictable — the Traefik dashboard allowlist depends on it.

```bash
docker network create --subnet 172.24.0.0/16 traefik_proxy
```

Also by hand (Traefik and the mouse stack both join it as external):

```bash
docker network create --internal --subnet 10.24.25.0/28 traefik_mouse
```

## Secrets

Files in `traefik/secrets/` (gitignored, mounted at `/secrets`), never env values:

| File | Read by |
|---|---|
| `cf_dns_api_token` (65026, `0400`) | lego `CF_DNS_API_TOKEN_FILE` (Cloudflare DNS challenge) |
| `crowdsec_lapi_key` (pi:65026, `0640`) | `dynamic/crowdsec.yml` `crowdsecLapiKeyFile` |

## Entrypoints

| Name | Port | Who reaches it | Purpose |
|------|------|----------------|---------|
| `web` | 80 | public | HTTP→HTTPS redirect + ACME HTTP challenge |
| `websecure` | 443 | public (Cloudflare tunnel) | every `holy-grail.ch` service |
| `internal` | 8080 (not published) | Prometheus only, over the internal `traefik_metrics` network | `/metrics` |
| `langtool` | 8443 | public (direct forward) | the two ddns services below |

| Service | Host | Entrypoint | Login |
|---|---|---|---|
| LanguageTool | `lang-tool.ddns.net` | `langtool` | per-person token URL |
| WG-Chores | `wg-aemtli.ddns.net` (`dynamic/wg-chores.yml`) | `langtool` | outside SSO, owner's choice, app's household code; never route `wg-chores-sqliteweb` |

## Networks (H-2, 2026-10-25)

Public apps and crown jewels have their own network, shared only with Traefik (`traefik_<app>`, defined in `docker-compose.yaml`, Traefik `.3` on each). Traefik's default route and published ports stay on `traefik_proxy` (`gw_priority`, 172.24.255.3). Pinned: Authentik trusts `10.24.15.3`, Portainer `10.24.7.7`, VPN NAT `10.24.5.5`. Full list: `../_global/docs/container-hardening.md`. `traefik_mouse` (10.24.25.0/28, gluetun_mouse `.2`, ABR `.4`, importer `.5`) is created by hand, not by this compose. Other apps are still on `traefik_proxy`.

`langtool` exists so the external `:443` forward can point at it instead of the
shared `websecure` entrypoint. `lang-tool.ddns.net` is a direct-ingress service
(not behind Cloudflare), so forwarding external `443 → 192.168.1.2:443` let
anyone hit the home IP with a spoofed `Host:` and reach every `holy-grail.ch`
service, bypassing Cloudflare and exposing the origin. On `:8443` only the
LanguageTool and WG-Chores routers are bound, so a spoofed host there returns 404.

**Router change the owner must make (Zyxel), to close the bypass:**
1. Open the Zyxel admin page, go to the NAT / Port-Forward (virtual-server) list.
2. Find the existing rule forwarding external TCP **443** to **192.168.1.2 : 443**.
3. Change its internal port from **443** to **8443** (internal host stays
   `192.168.1.2`). Leave the external port **443**.
4. Save/apply.

During the transition the LanguageTool routers are bound to **both** `websecure`
and `langtool`, so access keeps working before and after the router change.
Once the router points `443 → :8443`, remove `websecure` from the LanguageTool
routers (`dynamic/languagetool.yml` + the gitignored `languagetool-token.yml`)
and `docker compose up -d` Traefik — that is the step that finally closes the
`:443` bypass.

## Routes to beefy

Forward auth first (`authentik@file`), then the wake gate `http://192.168.1.2:9001/gate?port=<backend port>`, so only a signed-in user wakes beefy (exception: Jellyfin apps, see `jellyfin.yml`). Traefik (`172.24.255.3`) may reach every beefy port (`_global/scripts/docker-user-lan-guard.sh`).

| Host | Backend | Reach | Group |
|---|---|---|---|
| `jellyfin`, `requests`, `tracker` | `:8096`, `:5055`, `:8010`/`:8011` | public | streaming groups (Authentik README) |
| `radarr`, `sonarr`, `prowlarr`, `bazarr`, `qbittorrent`, `sabnzbd` | `:7878`, `:8989`, `:9696`, `:6767`, `:8080`, `:8081` | LAN + VPN | `streaming-admins` |
| `vpn-status-beefy` | `:8087` | LAN + VPN | `homelab-admins` |
| `dt` (Dependency-Track, `dt.yml`) | `:8090` | public | `homelab-admins`, then DT's own Holy Grail login |

## Routes to the mouse stack (fastpi audiobooks)

Over `traefik_mouse` to `gluetun_mouse` (`10.24.25.2`). LAN + VPN only (`local-networks@file`, no public DNS), then `authentik@file`; the apps trust only Traefik's `10.24.25.3`.

| Host | Backend | Group | App login |
|---|---|---|---|
| `qbittorrent-audiobooks` | `:8080` qbittorrent_mouse | `streaming-admins` | bypassed for `10.24.25.3/32`, Referer stripped |
| `sabnzbd-audiobooks` | `:8081` sabnzbd | `streaming-admins` | none; `local_ranges` + `host_whitelist` in `sabnzbd.ini` |
| `vpn-status-mouse` | `port-updater:8087` | `homelab-admins` | Basic, injected by Authentik |
| `prowlarr-audiobooks` | `:9696` prowlarr_mouse | `streaming-admins` | External (Holy Grail only) |
| `books` | ABR `10.24.25.4:8000` (Docker/Audiobook-Requests) | `streaming-requesters` | **public** (Cloudflare tunnel, like `requests`; no `local-networks@file`), ABR OIDC (`books-login`), trusts X-Forwarded-* from `10.24.25.3` only |

`traefik_mouse` members: gluetun_mouse `.2`, Traefik `.3`, audiobookrequest `.4`, audiobook-importer `.5` (ABR and the importer reach Prowlarr `:9696` and qBittorrent `:8080` here; the importer logs in to qBittorrent, only `.3` is bypassed).

## Client IPs

Every backend, `crowdsec@file` and `default-rate-limit` see **one** address in `X-Forwarded-For`: the real client. Set by `real-ip@file` (own local plugin `traefik/plugins-local/src/github.com/tomigorn/realip`, stdlib only, no download), first middleware on `websecure`, `langtool`, `internal`.

| Request arrives from | Client IP used |
|---|---|
| `172.24.0.1` (Cloudflare tunnel; also host/container hairpins) | `Cf-Connecting-Ip` (Cloudflare always overwrites it) |
| anything else (LAN, VPN `10.24.5.5`) | connection address |

Connection address Traefik sees, measured 2026-10-24 (`userland-proxy: true`, the default; `false` was tried and reverted because host requests then arrived as `172.24.0.1` and LAN-only routes returned 403 from the host):

| Source | Arrives as |
|---|---|
| cloudflared (`infra__cloudflare_default`, tunnel ingress `https://192.168.1.2:443`) | `172.24.0.1` |
| host processes and host-network containers (`curl https://192.168.1.2`) | `192.168.1.2` |
| containers whose default route is another network (authentik-server, prometheus) | `172.24.0.1` |
| containers whose default route is `traefik_proxy` (claude-mockups) | their own `172.24.x.y` |
| LAN clients | their LAN IP |
| VPN clients (wg-easy DNAT to `10.24.5.3` on `traefik_wg`) | `10.24.5.5` |

| Consumer | How it picks the IP |
|---|---|
| Authentik | leftmost XFF, trusts only `10.24.15.3` (Traefik on `traefik_authentik`, see [Authentik README](../Authentik/README.md#client-ip-audit-log-reputation-policy)) |
| `default-rate-limit` | `sourceCriterion.ipStrategy.depth: 1` (+ `ipv6Subnet: 64`) = one bucket per client; before 2026-10-24 the whole internet shared the `172.24.0.1` bucket |
| `crowdsec@file` | rightmost XFF from `172.24.0.1` = the same IP |
| `local-networks@file` | connection address only, headers never count |
| access log | raw incoming chain (`spoofed, real`); the rightmost entry is the real one |

Why a plugin: Traefik cannot rewrite `X-Forwarded-For` itself, and `forwardedHeaders.trustedIPs` keeps the client-supplied left part. Test (spoof must not show up): `curl -s --resolve sso.holy-grail.ch:443:$(dig +short @1.1.1.1 sso.holy-grail.ch | head -1) -H 'X-Forwarded-For: 203.0.113.77' https://sso.holy-grail.ch/-/health/live/; docker logs --since 1m authentik-server | grep -o '"remote":"[^"]*"' | tail -1`

## Updating Traefik

Run before every Traefik bump (the image is pinned in `docker-compose.yaml`):

```bash
scripts/traefik-plugin-test.sh v3.7.17   # the NEW tag; exit 0 = safe to bump
```

Throwaway containers on their own network (no host ports, removed afterwards): the given Traefik tag with both local plugins (ro), the repo's `experimental` block + `websecure` middlewares + `real-ip.yml`/`crowdsec.yml` (IPs adapted), `traefik/whoami:v1.11.0` as echo, a mock CrowdSec LAPI (`caddy:2.11.7-alpine`) banning two TEST-NET IPs. The real CrowdSec is never touched.

| Check | Expected |
|---|---|
| log | `Plugins loaded` lists `realip` + `crowdsec-bouncer`, no error |
| Cf-Connecting-Ip from the gateway (v4 + v6) | backend sees that IP (spoofed XFF dropped) |
| request from another container | its own IP, Cf-Connecting-Ip ignored |
| banned IPv4/IPv6 | 403 (also proves the key file is read) |
| clean IPv4/IPv6 | 200 |

`_global/scripts/update-project.sh Traefik pull` runs it with the tag from the compose file and stops before changing anything if it fails. After the bump: `docker logs traefik`, `_global/scripts/smoke-test.sh` (it pins the expected version: update `traefik version` there).

## Access log rotation

`logrotate/traefik` rotates `traefik/logs/access.log` (daily or at 100 MB, 14 kept, compressed with `delaycompress` so CrowdSec can finish the old file). `postrotate` sends `USR1` to Traefik, which reopens and recreates the file (no restart); CrowdSec's file tail follows the new file.

| Task | Command |
|---|---|
| Install / update | `sudo install -m 0644 -o root -g root logrotate/traefik /etc/logrotate.d/traefik` |
| Dry run | `sudo logrotate -d /etc/logrotate.d/traefik` |
| Force one rotation | `sudo logrotate -f /etc/logrotate.d/traefik` |

Runs from the system `logrotate.timer`. The file is not created by logrotate (`nocreate`) because uid 65026 has no host user name; Traefik creates it itself.

## Authentik SSO integration

[Authentik](../Authentik/README.md) is the homelab IdP, reached at
`sso.holy-grail.ch`.

`dynamic/sso.yml` routes `sso.holy-grail.ch` (websecure) →
`authentik-server:9000` — the Authentik login UI and API, reached via
Cloudflare Tunnel (`192.168.1.2:443`, HTTPS, No-TLS-Verify) → Traefik → here.

This is a vanilla Authentik install (login + outbound email only). There is no
forward-auth middleware and no pre-provisioned OIDC wiring in Traefik; apps that
use Authentik are configured directly in the Authentik web UI.
