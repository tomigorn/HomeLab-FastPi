# Homelab admin SSO: design

Date: 2026-10-18. Status: approved (the user auto-approves specs, per CLAUDE.md).

## Goal

Six admin tools sign in through Authentik (`sso.holy-grail.ch`), and only members
of the Authentik group **`homelab-admins`** get in:

- Traefik dashboard
- Grafana
- Portainer
- AdGuard Home
- wg-easy
- Home Assistant

Each tool keeps **exactly one break-glass way in** that works when Authentik is
down. The one exception is wg-easy: the user asked for its password login to be
switched off, so its break-glass is a config flip on the host (see section 5).

## Decisions that apply to all six

1. **Gate.** Each tool gets an Authentik Application with a **group binding to
   `homelab-admins`**. This binding is the access control. Only Grafana and Home
   Assistant also read the `groups` claim themselves, to decide the role.
2. **One stable HTTPS hostname per tool, LAN + VPN only.** Each tool gets
   `<name>.holy-grail.ch` on the `websecure` entrypoint, with a `cloudflare`
   certificate (DNS-01, so no public DNS record is needed) and `local-networks@file`
   as the **first** middleware.
   - OIDC needs a fixed redirect URL, and forward-auth cookies need HTTPS.
   - AdGuard's existing `*.holy-grail.ch → 192.168.1.2` rewrite makes these names
     resolve for VPN clients and for LAN clients that use AdGuard. LAN devices that
     do not use AdGuard need the user's pending Zyxel DHCP DNS change
     (→ 192.168.1.2). Nothing is published on Cloudflare.
   - Internet traffic that arrives through the tunnel comes from 172.24.0.1, which
     `local-networks@file` rejects with 403.

   | Tool | New host | Method | Break-glass |
   |---|---|---|---|
   | Traefik dashboard | `traefik.holy-grail.ch` | forward auth (`authentik@file`) | existing `fastpi.homelab` router on `internal` with basicAuth, unchanged |
   | Grafana | `grafana.holy-grail.ch` | native generic OAuth | local `admin` at `/login?disableAutoLogin=true` (also via LAN `:3001`) |
   | Portainer | `portainer.holy-grail.ch` | native OAuth (CE "Custom") | initial admin (user ID 1) with its internal password, on `:9443` or the new host |
   | AdGuard Home | `adguard.holy-grail.ch` | forward auth + Authentik injects HTTP Basic credentials for a dedicated AdGuard user | the user's existing AdGuard login on LAN `:3080` |
   | wg-easy | `wg-easy.holy-grail.ch` | native OIDC (new in 15.4.0) | `DISABLE_PASSWORD_AUTH=false` + restart, from the host shell |
   | Home Assistant | `ha.holy-grail.ch` | `hass-oidc-auth` v1.2.1 custom component | HA owner account with its local password (never linked to OIDC) |

3. **The shared `authentik@file` middleware stays unchanged.** Adding
   `Authorization` to its `authResponseHeaders` would strip clients' own
   Authorization headers on every route that uses it. That is Traefik behaviour
   (`forward.go`: listed headers are deleted from the request first). AdGuard gets
   its own middleware, `authentik-basic@file`.
4. **Authentik config as code.** One idempotent script,
   `Authentik/scripts/provision-admin-sso.py`, run via `ak shell`. Pattern:
   `Avatar-Picker/scripts/provision-authentik.py`. The script creates:
   - the providers and Applications
   - the group bindings to `homelab-admins`
   - the outpost assignment for the two proxy providers
   - the `email_verified: True` scope mapping for wg-easy

   Client secrets are generated in Authentik and printed to stdout as
   `<APP>_CLIENT_ID=` / `<APP>_CLIENT_SECRET=`. They are written only into each
   project's gitignored `.env`, never into git, logs or chat. Each `.env.example`
   gets the same variables blanked, with the same comments.
5. **Containers reach the IdP on the LAN.** Every OIDC client container gets
   `extra_hosts: ["sso.holy-grail.ch:192.168.1.2"]`, as Jellyfin has, so discovery
   and token calls never U-turn through Cloudflare. HA runs with host networking,
   which already resolves through AdGuard (127.0.0.1) → 192.168.1.2. Verify this
   with `curl` from inside each container.
6. **Grant = the binding; role = admin.** Every member of `homelab-admins` gets
   admin rights in each tool. There are no viewer tiers (YAGNI).

## Per-tool design

### 1. Traefik dashboard
- **New routers in `dashboard.yml`:**
  - `traefik-dashboard-sso`:
    - Host `traefik.holy-grail.ch`, paths `/api` + `/dashboard`, service `api@internal`.
    - Middlewares `[local-networks@file, authentik@file]`.
    - Plus a redirect from `/` → `/dashboard/`.
  - The usual outpost companion router: `PathPrefix(/outpost.goauthentik.io/)`,
    higher priority, no app middlewares, service `authentik@file`.
    `local-networks@file` is also applied to it.
- **Existing `dashboard` router** (`fastpi.homelab` on `internal`, with basicAuth)
  stays as the break-glass.
- **Authentik:** proxy provider `traefik-dashboard-proxy`
  (`forward_single`, external host `https://traefik.holy-grail.ch`), plus an
  Application and the binding.

### 2. Grafana
- **Env:**
  - `GF_SERVER_ROOT_URL=https://grafana.holy-grail.ch`
  - generic-OAuth settings per the research report:
    - PKCE and refresh token on
    - `groups_attribute_path=groups`, `allowed_groups=homelab-admins`
    - `role_attribute_path=contains(groups[*], 'homelab-admins') && 'Admin'`
    - `role_attribute_strict=true`, `allow_assign_grafana_admin=true` with
      `GrafanaAdmin`
    - `auto_login=true`, signout redirect to Authentik end-session
  - Client id/secret come from `.env`.
- **Keep the login form** (do not set `disable_login_form`). That is the break-glass.
- **Router:** `grafana.holy-grail.ch` → `grafana:3000`. Grafana must join
  `traefik_proxy` if it is not on it yet. The `:3001` LAN port stays.
- **Authentik:** confidential OAuth2 provider `grafana`.
  - Redirect `https://grafana.holy-grail.ch/login/generic_oauth` (strict).
  - Post-logout `https://grafana.holy-grail.ch/logout`.
- **Gotcha:** the local admin login/email must differ from the Authentik user
  (`tomigorn` / tomigorn@gmail.com). Check this before enabling.

### 3. Portainer CE 2.45.2
- **Router:** `portainer.holy-grail.ch` → `https://portainer:9443`, using a
  serversTransport with `insecureSkipVerify` (self-signed backend). If the
  container exposes plain `:9000`, use `http://portainer:9000` instead.
- **OAuth settings** (configured through Portainer's API, as the initial admin):
  - Custom provider, authorize/token/userinfo URLs on `sso.holy-grail.ch`.
  - Redirect `https://portainer.holy-grail.ch/`, user identifier
    `preferred_username`, scopes `openid profile email` (separated by spaces).
  - SSO on, **automatic user provisioning off**.
- **Admin mapping:** CE cannot map groups to roles, so a Portainer user
  `tomigorn`, role administrator, is pre-created before OAuth is enabled.
- **Break-glass:** user ID 1 (the initial admin) can always log in internally.
  CE has no switch to turn this off.
- **Blocker:** if the Portainer initial-admin credentials are not available to
  Claude, the OAuth settings are a manual UI step for the user. The plan carries
  those exact field values.

### 4. AdGuard Home
- **Router:** `adguard.holy-grail.ch` → AdGuard web UI on the host. AdGuard runs
  with host networking, so the target is `http://192.168.1.2:3080`.
  - Middlewares `[local-networks@file, authentik-basic@file]`, plus an outpost
    companion router.
- **New middleware** `authentik-basic` in `authentik-forwardauth.yml`: identical
  to `authentik`, plus `Authorization` in `authResponseHeaders`.
- **Credentials:** a new AdGuard user `authentik-proxy` is added to `users:` with a
  long random password, as a bcrypt hash. Its plaintext goes into Authentik as
  attributes on the provider/user, read via HTTP-Basic username/password
  attribute keys.
  - The user's own AdGuard login stays untouched (break-glass on `:3080`).
  - The AdGuard config is edited only with the container stopped.
- **Authentik:** proxy provider `adguard-proxy` (`forward_single`), with
  `basic_auth_enabled`, plus an Application and the binding.

### 5. wg-easy 15.4.0
- **Env:**
  - `OAUTH_PROVIDERS=oidc`, `OAUTH_OIDC_NAME=authentik`
  - `OAUTH_OIDC_SERVER=https://sso.holy-grail.ch/application/o/wg-easy/`
  - client id/secret from `.env`
  - `OAUTH_AUTO_REGISTER=false` (auto-registered users would become admins)
  - `OAUTH_AUTO_LAUNCH=oidc`
- **Linking:** the existing wg-easy admin's email is set to the Authentik user's
  email through the wg-easy API. The first OIDC login then links automatically.
- **Router:** one hostname only, `wg-easy.holy-grail.ch` on `websecure` with a
  cloudflare cert. The redirect URI is built from the Host header, so the two old
  `wg-easy.fastpi.homelab` routers are removed.
- **Lockdown (stage 2):** once the user confirms one OIDC login works:
  1. Set `DISABLE_PASSWORD_AUTH=true` and recreate the container.
  2. Remove `WG_EASY_ADMIN_PASSWORD` (and its username line, if it is only a
     record) from `.env` and `.env.example`. The `INIT_*` vars are read only on
     first start.
  3. Document the break-glass in the project README.

  Scripts that use Basic auth against the wg-easy API stop working. A grep in
  stage 2 confirms there are none.
- **Authentik:** confidential OAuth2 provider `wg-easy`.
  - Redirects `/api/auth/oidc/callback` and `/api/auth/oidc/link` (strict).
  - Custom scope mapping "email (verified)" returning
    `{"email": request.user.email, "email_verified": True}`, replacing the default
    email mapping on this provider only. Addresses are trusted because enrolment
    is invite-only and email-verified.

### 6. Home Assistant
- **Router:** `ha.holy-grail.ch` → `http://192.168.1.2:8123`.
  - HA `http:` gets `use_x_forwarded_for: true` plus `trusted_proxies` = Traefik's
    address on `traefik_proxy`.
  - The existing `http://192.168.1.2:8123` keeps working, so the Companion apps are
    unaffected.
- **Install:** `custom_components/auth_oidc` from the pinned v1.2.1 **release
  zip**. Verify its checksum before unpacking, and unpack it into an empty
  directory.
- **Config:** `auth_oidc:` with a public client and the discovery URL.
  - `roles: {admin: homelab-admins, user: homelab-admins}`
  - `default_redirect: true`; backup login via `/?skip_oidc_redirect=true`
  - `automatic_person_creation: true`; no automatic linking
  - The OIDC user is a new HA admin user. The owner account stays local-only.
- **Authentik:** **public** OAuth2 provider `home-assistant`, redirect
  `https://ha.holy-grail.ch/auth/oidc/callback`.
- **Gotcha:** roles are set only at first login.

## Order and staging

Least risky first:

1. Traefik dashboard
2. Grafana
3. Portainer
4. AdGuard
5. wg-easy
6. HA

**Stage 1** (Claude, no user action needed): each tool gains SSO **alongside** its
existing login. Nothing old is removed, except the wg-easy `.homelab` routers.

**Stage 2** (after the user confirms one SSO login per tool):
- wg-easy password-auth lockdown
- `.env` cleanup
- README break-glass notes

## Testing

- **Per tool, automated:**
  - From outside, the tunnel path (`curl` with a 172.24.0.1-equivalent, i.e. via
    Cloudflare) returns 403.
  - From the LAN, an unauthenticated request redirects (302) to
    `sso.holy-grail.ch`, or to the tool's own OIDC login.
  - The break-glass path still answers.
  - The OIDC discovery URL is reachable from inside the container.
- `_global/scripts/smoke-test.sh` gains these checks.
- **The user does once per tool:** log in through SSO with `tomigorn`, then log
  in once through the break-glass path.

## Out of scope

- Viewer or non-admin roles.
- Group-to-role mapping in Portainer (Business Edition only).
- Removing the break-glass logins (other than wg-easy, by request).
- Making any of the six tools public.
