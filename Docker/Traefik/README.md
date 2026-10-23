Create the shared proxy network before starting any services.
The subnet must be pinned so the gateway IP (`172.24.0.1`) is always
predictable — the Traefik dashboard allowlist depends on it.

```bash
docker network create --subnet 172.24.0.0/16 traefik_proxy
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
| `internal` | 8080 | LAN/VPN | dashboard only (IP-allowlisted) |
| `langtool` | 8443 | public (direct forward) | LanguageTool only (`lang-tool.ddns.net`) |

`langtool` exists so the external `:443` forward can point at it instead of the
shared `websecure` entrypoint. `lang-tool.ddns.net` is a direct-ingress service
(not behind Cloudflare), so forwarding external `443 → 192.168.1.2:443` let
anyone hit the home IP with a spoofed `Host:` and reach every `holy-grail.ch`
service, bypassing Cloudflare and exposing the origin. On `:8443` only the
LanguageTool routers are bound, so a spoofed host there returns 404.

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

## Client IPs

Every backend, `crowdsec@file` and `default-rate-limit` see **one** address in `X-Forwarded-For`: the real client. Set by `real-ip@file` (own local plugin `traefik/plugins-local/src/github.com/tomigorn/realip`, stdlib only, no download), first middleware on `websecure`, `langtool`, `internal`.

| Request arrives from | Client IP used |
|---|---|
| `172.24.0.1` (Cloudflare tunnel; also host/container hairpins) | `Cf-Connecting-Ip` (Cloudflare always overwrites it) |
| anything else (LAN, VPN `172.24.255.5`) | connection address |

| Consumer | How it picks the IP |
|---|---|
| Authentik | leftmost XFF, trusts only `172.24.255.3` (see [Authentik README](../Authentik/README.md#client-ip-audit-log-reputation-policy)) |
| `default-rate-limit` | `sourceCriterion.ipStrategy.depth: 1` (+ `ipv6Subnet: 64`) = one bucket per client; before 2026-10-24 the whole internet shared the `172.24.0.1` bucket |
| `crowdsec@file` | rightmost XFF from `172.24.0.1` = the same IP |
| `local-networks@file` | connection address only, headers never count |
| access log | raw incoming chain (`spoofed, real`); the rightmost entry is the real one |

Why a plugin: Traefik cannot rewrite `X-Forwarded-For` itself, and `forwardedHeaders.trustedIPs` keeps the client-supplied left part. Test (spoof must not show up): `curl -s --resolve sso.holy-grail.ch:443:$(dig +short @1.1.1.1 sso.holy-grail.ch | head -1) -H 'X-Forwarded-For: 203.0.113.77' https://sso.holy-grail.ch/-/health/live/; docker logs --since 1m authentik-server | grep -o '"remote":"[^"]*"' | tail -1`

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
