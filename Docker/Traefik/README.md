Create the shared proxy network before starting any services.
The subnet must be pinned so the gateway IP (`172.24.0.1`) is always
predictable — the Traefik dashboard allowlist depends on it.

```bash
docker network create --subnet 172.24.0.0/16 traefik_proxy
```

## Authentik SSO integration

[Authentik](../Authentik/README.md) is the homelab IdP. It plugs into Traefik in
two independent ways — pick one per app (full guide:
`Docker/Authentik/docs/auth-integration-modes.md`).

### 1. Public route to Authentik itself
`dynamic/sso.yml` — routes `sso.holy-grail.ch` (websecure) →
`authentik-server:9000`. This is the login UI + OIDC endpoints, reached via
Cloudflare Tunnel (`192.168.1.2:443`, HTTPS, No-TLS-Verify) → Traefik → here.

### 2. OIDC apps (Mode 2 — app has its own login)
Nothing special in Traefik. The app just needs to be publicly routed normally
(e.g. `audiobookshelf.yml`); it talks to Authentik directly over the public
`sso.holy-grail.ch` endpoints. **Portainer** and **Audiobookshelf** use this.
Portainer is additionally routed VPN/LAN-only (`portainer.yml`, `internal`
entrypoint + IP allowlist) because it controls the Docker socket.

### 3. Forward-auth gate (Mode 1 — app has NO login of its own)
For apps that can't authenticate themselves, Traefik gates them with an
Authentik `forwardAuth` middleware:

- **`dynamic/authentik-forwardauth.yml`** — defines the reusable `authentik`
  middleware (points at the embedded outpost
  `authentik-server:9000/outpost.goauthentik.io/auth/traefik`, forwards the
  `X-authentik-*` user/group headers). It is **inert until a router references
  it**, so it's safe to keep loaded.
- **`dynamic/_example-routes.yml`** — two copy-paste templates (all commented):
  *Example 1* a normal public HTTPS service, *Example 2* the same service with
  `- authentik` added to the router (plus the optional `/outpost.goauthentik.io/`
  router needed only in single-application mode). To gate a new app: copy
  Example 2, swap in the real host/backend.

> ⚠️ The middleware is only half the wiring. It stays inert (auth subrequest
> ~400) until the **Authentik side** exists — a Proxy Provider + Application
> assigned to the embedded outpost. That is **not built yet**; see
> `Docker/Authentik/docs/auth-integration-modes.md` for how to add it. Don't
> double-gate OIDC apps (Portainer/ABS) with this.
