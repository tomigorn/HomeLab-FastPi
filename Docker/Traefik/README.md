Create the shared proxy network before starting any services.
The subnet must be pinned so the gateway IP (`172.24.0.1`) is always
predictable — the Traefik dashboard allowlist depends on it.

```bash
docker network create --subnet 172.24.0.0/16 traefik_proxy
```

## Authentik SSO integration

[Authentik](../Authentik/README.md) is the homelab IdP, reached at
`sso.holy-grail.ch`.

`dynamic/sso.yml` routes `sso.holy-grail.ch` (websecure) →
`authentik-server:9000` — the Authentik login UI and API, reached via
Cloudflare Tunnel (`192.168.1.2:443`, HTTPS, No-TLS-Verify) → Traefik → here.

This is a vanilla Authentik install (login + outbound email only). There is no
forward-auth middleware and no pre-provisioned OIDC wiring in Traefik; apps that
use Authentik are configured directly in the Authentik web UI.
