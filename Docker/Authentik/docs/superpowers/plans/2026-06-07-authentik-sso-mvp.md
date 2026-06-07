# Authentik SSO MVP Implementation Plan

> **For agentic workers:** Infrastructure plan. Steps use checkbox (`- [ ]`) syntax. "Tests" are docker/curl verifications with expected output. Tasks are tagged **[AGENT]** (Claude does it) or **[USER]** (Tomi does it — external dashboards / app web-UIs Claude can't click).

**Goal:** Stand up Authentik 2026.5 as an OIDC provider and inject SSO login into Portainer (VPN/LAN-only) and Audiobookshelf (public), with `admin` and `streaming` groups.

**Architecture:** Fresh `Authentik` compose project (postgres + server + worker, no Redis), fronted by existing Traefik via a new `sso.holy-grail.ch` file-route. All Authentik objects (groups, OIDC providers, applications, group bindings, ABS role claim) are codified in a declarative blueprint applied at startup. Portainer gets a VPN/LAN-only Traefik route. App-side OIDC is pasted into each app's settings by the user using exact values this plan/Claude provides.

**Tech Stack:** Docker Compose, Authentik 2026.5.2, PostgreSQL 16, Traefik v3.7 (file provider), Cloudflare Tunnel (dashboard-managed).

**Conventions:** Repo root `/home/pi/Projects` (git, branch `main`). Docker projects under `/home/pi/Projects/Docker`, each with the 4-file structure (`docker-compose.yaml`, `.env.example`, `.env`, `.gitignore`). `.env` and secrets are gitignored. Deploy-side files are left for the user to commit on their cadence; only docs (spec/plan) are committed by Claude.

---

## File Structure

**Create:**
- `Docker/Authentik/docker-compose.yaml` — postgres + server + worker
- `Docker/Authentik/.env.example` — committed template (placeholders)
- `Docker/Authentik/.env` — real secrets (gitignored)
- `Docker/Authentik/.gitignore` — per sample + data dirs
- `Docker/Authentik/blueprints/mvp.yaml` — groups, providers, apps, bindings, ABS role mapping
- `Docker/Traefik/traefik/dynamic/sso.yml` — public route for Authentik
- `Docker/Traefik/traefik/dynamic/portainer.yml` — internal (VPN/LAN) route for Portainer

**Modify:**
- `Docker/Portainer/docker-compose.yaml` — join `traefik_proxy` network

**Runtime data (gitignored, created by Docker):**
- `Docker/Authentik/media/`, `Docker/Authentik/certs/`, postgres named volume

---

## Task 1 [AGENT]: Scaffold the Authentik project + generate secrets

**Files:** Create `Docker/Authentik/.gitignore`, `.env.example`, `.env`, `docker-compose.yaml`.

- [ ] **Step 1: Create `.gitignore`** (copy the repo sample + ignore runtime data)

```gitignore
# Environment files (contain secrets) — keep .env.example tracked
.env
.env.*
!.env.example

# Keys & certificates
*.key
*.pem
*.crt
*.cert
*.csr
*.p12
*.pfx

# Credentials, secrets & tokens
secrets/
*.secret
*.token

# Authentik runtime data
media/
certs/
custom-templates/
postgres-data/
```

- [ ] **Step 2: Create `.env.example`** (committed template, placeholders only)

```dotenv
COMPOSE_PROJECT_NAME=authentik

# --- Authentik image ---
AUTHENTIK_TAG=2026.5.2

# --- PostgreSQL ---
PG_USER=authentik
PG_DB=authentik
PG_PASS=

# --- Authentik core ---
AUTHENTIK_SECRET_KEY=
AUTHENTIK_BOOTSTRAP_PASSWORD=
AUTHENTIK_BOOTSTRAP_TOKEN=
AUTHENTIK_BOOTSTRAP_EMAIL=admin@holy-grail.ch

# --- OIDC client credentials (injected into blueprint, pasted into apps) ---
ABS_OIDC_CLIENT_ID=audiobookshelf
ABS_OIDC_CLIENT_SECRET=
PORTAINER_OIDC_CLIENT_ID=portainer
PORTAINER_OIDC_CLIENT_SECRET=
```

- [ ] **Step 3: Generate real secrets into `.env`**

Run:
```bash
cd /home/pi/Projects/Docker/Authentik
umask 077
{
  echo "COMPOSE_PROJECT_NAME=authentik"
  echo "AUTHENTIK_TAG=2026.5.2"
  echo "PG_USER=authentik"
  echo "PG_DB=authentik"
  echo "PG_PASS=$(openssl rand -hex 24)"
  echo "AUTHENTIK_SECRET_KEY=$(openssl rand -base64 60 | tr -d '\n')"
  echo "AUTHENTIK_BOOTSTRAP_PASSWORD=$(openssl rand -hex 16)"
  echo "AUTHENTIK_BOOTSTRAP_TOKEN=$(openssl rand -hex 32)"
  echo "AUTHENTIK_BOOTSTRAP_EMAIL=admin@holy-grail.ch"
  echo "ABS_OIDC_CLIENT_ID=audiobookshelf"
  echo "ABS_OIDC_CLIENT_SECRET=$(openssl rand -hex 32)"
  echo "PORTAINER_OIDC_CLIENT_ID=portainer"
  echo "PORTAINER_OIDC_CLIENT_SECRET=$(openssl rand -hex 32)"
} > .env
chmod 600 .env
```
Expected: `.env` exists with all values filled.

- [ ] **Step 4: Create `docker-compose.yaml`**

```yaml
# =========================================================
# Services ================================================
# =========================================================
services:
# #########################################################
# PostgreSQL ##############################################
# #########################################################
  postgresql:
    image: docker.io/library/postgres:16-alpine
    container_name: authentik-postgresql
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -d $${POSTGRES_DB} -U $${POSTGRES_USER}"]
      start_period: 20s
      interval: 30s
      retries: 5
      timeout: 5s
    volumes:
      - ./postgres-data:/var/lib/postgresql/data
    environment:
      POSTGRES_USER: ${PG_USER}
      POSTGRES_DB: ${PG_DB}
      POSTGRES_PASSWORD: ${PG_PASS}
    networks:
      - authentik_internal

# #########################################################
# Authentik Server ########################################
# #########################################################
  server:
    image: ghcr.io/goauthentik/server:${AUTHENTIK_TAG}
    container_name: authentik-server
    restart: unless-stopped
    command: server
    environment:
      AUTHENTIK_SECRET_KEY: ${AUTHENTIK_SECRET_KEY}
      AUTHENTIK_POSTGRESQL__HOST: postgresql
      AUTHENTIK_POSTGRESQL__USER: ${PG_USER}
      AUTHENTIK_POSTGRESQL__NAME: ${PG_DB}
      AUTHENTIK_POSTGRESQL__PASSWORD: ${PG_PASS}
      AUTHENTIK_BOOTSTRAP_PASSWORD: ${AUTHENTIK_BOOTSTRAP_PASSWORD}
      AUTHENTIK_BOOTSTRAP_TOKEN: ${AUTHENTIK_BOOTSTRAP_TOKEN}
      AUTHENTIK_BOOTSTRAP_EMAIL: ${AUTHENTIK_BOOTSTRAP_EMAIL}
    volumes:
      - ./media:/media
      - ./custom-templates:/templates
      - ./blueprints:/blueprints/custom:ro
    depends_on:
      postgresql:
        condition: service_healthy
    networks:
      - authentik_internal
      - traefik_proxy

# #########################################################
# Authentik Worker ########################################
# #########################################################
  worker:
    image: ghcr.io/goauthentik/server:${AUTHENTIK_TAG}
    container_name: authentik-worker
    restart: unless-stopped
    command: worker
    environment:
      AUTHENTIK_SECRET_KEY: ${AUTHENTIK_SECRET_KEY}
      AUTHENTIK_POSTGRESQL__HOST: postgresql
      AUTHENTIK_POSTGRESQL__USER: ${PG_USER}
      AUTHENTIK_POSTGRESQL__NAME: ${PG_DB}
      AUTHENTIK_POSTGRESQL__PASSWORD: ${PG_PASS}
      AUTHENTIK_BOOTSTRAP_PASSWORD: ${AUTHENTIK_BOOTSTRAP_PASSWORD}
      AUTHENTIK_BOOTSTRAP_TOKEN: ${AUTHENTIK_BOOTSTRAP_TOKEN}
      AUTHENTIK_BOOTSTRAP_EMAIL: ${AUTHENTIK_BOOTSTRAP_EMAIL}
    user: root
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./media:/media
      - ./certs:/certs
      - ./custom-templates:/templates
      - ./blueprints:/blueprints/custom:ro
    depends_on:
      postgresql:
        condition: service_healthy
    networks:
      - authentik_internal

# =========================================================
# Networks ================================================
# =========================================================
networks:
  authentik_internal:
    driver: bridge
  traefik_proxy:
    external: true

# =========================================================
# Volumes =================================================
# =========================================================
```

- [ ] **Step 5: Validate compose config**

Run: `cd /home/pi/Projects/Docker/Authentik && docker compose config >/dev/null && echo OK`
Expected: `OK` (no interpolation/syntax errors).

- [ ] **Step 6: Create the empty blueprints dir placeholder**

Run: `mkdir -p /home/pi/Projects/Docker/Authentik/blueprints`
(Blueprint file added in Task 4 so first boot is clean.)

---

## Task 2 [AGENT]: Boot Authentik core and verify health (local, no public URL yet)

**Files:** none (runtime only).

- [ ] **Step 1: Pull + start**

Run: `cd /home/pi/Projects/Docker/Authentik && docker compose up -d`
Expected: `postgresql`, `server`, `worker` created/started.

- [ ] **Step 2: Wait for healthy server**

Run:
```bash
for i in $(seq 1 30); do
  s=$(docker inspect -f '{{.State.Health.Status}}' authentik-server 2>/dev/null || echo none)
  echo "attempt $i: $s"; [ "$s" = "healthy" ] && break; sleep 5
done
```
Expected: ends at `healthy` (server has a built-in healthcheck; may take 1-3 min on a Pi).

- [ ] **Step 3: Curl the local server through the traefik_proxy network**

Run: `docker run --rm --network traefik_proxy curlimages/curl:latest -sS -o /dev/null -w "%{http_code}\n" http://authentik-server:9000/-/health/live/`
Expected: `204` (liveness) — confirms the server answers on the proxy network.

- [ ] **Step 4: Confirm no Redis / no errors in logs**

Run: `docker logs authentik-server 2>&1 | tail -30`
Expected: startup completes; no fatal DB/secret-key errors. (Redis absence is normal in 2026.5.)

---

## Task 3 [USER then AGENT]: Publish Authentik at sso.holy-grail.ch

- [ ] **Step 1 [AGENT]: Create the Traefik route `Docker/Traefik/traefik/dynamic/sso.yml`**

```yaml
http:
  routers:
    authentik:
      rule: "Host(`sso.holy-grail.ch`)"
      entryPoints: ["websecure"]
      priority: 1
      service: authentik
      middlewares:
        - authentik-secure-headers
      tls:
        certResolver: cloudflare

  middlewares:
    authentik-secure-headers:
      headers:
        stsSeconds: 31536000
        stsIncludeSubdomains: true
        stsPreload: true
        contentTypeNosniff: true
        referrerPolicy: "strict-origin-when-cross-origin"
        frameDeny: false
        customFrameOptionsValue: "SAMEORIGIN"
        permissionsPolicy: "camera=(), microphone=(), geolocation=()"
        customResponseHeaders:
          Server: ""

  services:
    authentik:
      loadBalancer:
        servers:
          - url: "http://authentik-server:9000"
        passHostHeader: true
```
(Traefik file provider watches `/dynamic`; no restart needed.)

- [ ] **Step 2 [USER]: Create the Cloudflare Tunnel public hostname**
  In Cloudflare Zero Trust → Networks → Tunnels → (your tunnel) → Public Hostnames → **Add**:
  - Subdomain `sso`, Domain `holy-grail.ch`
  - Service: **exactly mirror the `audiobookshelf.holy-grail.ch` entry** (same type/URL pointing at Traefik, e.g. `https://traefik:443` with TLS "No TLS Verify" if that's what the others use).
  Save.

- [ ] **Step 3 [AGENT]: Verify the public endpoint**

Run: `curl -sS -o /dev/null -w "%{http_code}\n" https://sso.holy-grail.ch/-/health/live/`
Expected: `204`. If `530/502`, the Cloudflare hostname or tunnel target is off — recheck Step 2.

- [ ] **Step 4 [USER]: First admin login**
  Visit `https://sso.holy-grail.ch/if/admin/` (or `/if/flow/initial-setup/`). Log in as `akadmin` with `AUTHENTIK_BOOTSTRAP_PASSWORD` from `.env`. Confirm the admin dashboard loads.
  *(Claude will print the password value from `.env` privately in chat.)*

---

## Task 4 [AGENT]: Apply the declarative blueprint (groups, providers, apps, bindings)

**Files:** Create `Docker/Authentik/blueprints/mvp.yaml`.

- [ ] **Step 1: Write the blueprint**

```yaml
version: 1
metadata:
  name: "MVP - SSO apps (Portainer + Audiobookshelf)"
  labels:
    blueprints.goauthentik.io/instantiate: "true"
context:
  abs_client_id: !Env [ABS_OIDC_CLIENT_ID, audiobookshelf]
  abs_client_secret: !Env ABS_OIDC_CLIENT_SECRET
  portainer_client_id: !Env [PORTAINER_OIDC_CLIENT_ID, portainer]
  portainer_client_secret: !Env PORTAINER_OIDC_CLIENT_SECRET
entries:
  # ---- Groups ----
  - model: authentik_core.group
    id: group-admin
    identifiers:
      name: admin
    attrs:
      name: admin
  - model: authentik_core.group
    id: group-streaming
    identifiers:
      name: streaming
    attrs:
      name: streaming

  # ---- Custom scope mapping: ABS role via group claim ----
  - model: authentik_providers_oauth2.scopemapping
    id: abs-groups
    identifiers:
      name: "ABS groups (role claim)"
      scope_name: groups
    attrs:
      name: "ABS groups (role claim)"
      scope_name: groups
      description: "Emits admin/user for Audiobookshelf role mapping"
      expression: |
        if ak_is_group_member(user, name="admin"):
            return {"groups": ["admin"]}
        return {"groups": ["user"]}

  # ---- Audiobookshelf provider + application ----
  - model: authentik_providers_oauth2.oauth2provider
    id: provider-abs
    identifiers:
      name: Audiobookshelf
    attrs:
      name: Audiobookshelf
      client_type: confidential
      client_id: !Context abs_client_id
      client_secret: !Context abs_client_secret
      authorization_flow: !Find [authentik_flows.flow, [slug, default-provider-authorization-implicit-consent]]
      invalidation_flow: !Find [authentik_flows.flow, [slug, default-provider-invalidation-flow]]
      signing_key: !Find [authentik_crypto.certificatekeypair, [name, "authentik Self-signed Certificate"]]
      redirect_uris:
        - matching_mode: strict
          url: "https://audiobookshelf.holy-grail.ch/auth/openid/callback"
        - matching_mode: strict
          url: "https://audiobookshelf.holy-grail.ch/auth/openid/mobile-redirect"
      property_mappings:
        - !Find [authentik_providers_oauth2.scopemapping, [managed, "goauthentik.io/providers/oauth2/scope-openid"]]
        - !Find [authentik_providers_oauth2.scopemapping, [managed, "goauthentik.io/providers/oauth2/scope-email"]]
        - !Find [authentik_providers_oauth2.scopemapping, [managed, "goauthentik.io/providers/oauth2/scope-profile"]]
        - !KeyOf abs-groups
  - model: authentik_core.application
    id: app-abs
    identifiers:
      slug: audiobookshelf
    attrs:
      name: Audiobookshelf
      slug: audiobookshelf
      provider: !KeyOf provider-abs
      meta_launch_url: "https://audiobookshelf.holy-grail.ch"

  # ---- Portainer provider + application ----
  - model: authentik_providers_oauth2.oauth2provider
    id: provider-portainer
    identifiers:
      name: Portainer
    attrs:
      name: Portainer
      client_type: confidential
      client_id: !Context portainer_client_id
      client_secret: !Context portainer_client_secret
      authorization_flow: !Find [authentik_flows.flow, [slug, default-provider-authorization-implicit-consent]]
      invalidation_flow: !Find [authentik_flows.flow, [slug, default-provider-invalidation-flow]]
      signing_key: !Find [authentik_crypto.certificatekeypair, [name, "authentik Self-signed Certificate"]]
      redirect_uris:
        - matching_mode: strict
          url: "https://portainer.fastpi.homelab"
      property_mappings:
        - !Find [authentik_providers_oauth2.scopemapping, [managed, "goauthentik.io/providers/oauth2/scope-openid"]]
        - !Find [authentik_providers_oauth2.scopemapping, [managed, "goauthentik.io/providers/oauth2/scope-email"]]
        - !Find [authentik_providers_oauth2.scopemapping, [managed, "goauthentik.io/providers/oauth2/scope-profile"]]
  - model: authentik_core.application
    id: app-portainer
    identifiers:
      slug: portainer
    attrs:
      name: Portainer
      slug: portainer
      provider: !KeyOf provider-portainer
      meta_launch_url: "https://portainer.fastpi.homelab"

  # ---- Access bindings (which group reaches which app) ----
  - model: authentik_policies.policybinding
    identifiers:
      target: !KeyOf app-portainer
      group: !KeyOf group-admin
      order: 0
    attrs:
      enabled: true
  - model: authentik_policies.policybinding
    identifiers:
      target: !KeyOf app-abs
      group: !KeyOf group-admin
      order: 0
    attrs:
      enabled: true
  - model: authentik_policies.policybinding
    identifiers:
      target: !KeyOf app-abs
      group: !KeyOf group-streaming
      order: 1
    attrs:
      enabled: true
```

- [ ] **Step 2: Make the blueprint env available to the worker**

The worker reads `!Env` from its own environment. The OIDC client vars are already in `server`/`worker` env? They are NOT yet — add them. Edit `Docker/Authentik/docker-compose.yaml` to add these four lines under BOTH `server.environment:` and `worker.environment:`:
```yaml
      ABS_OIDC_CLIENT_ID: ${ABS_OIDC_CLIENT_ID}
      ABS_OIDC_CLIENT_SECRET: ${ABS_OIDC_CLIENT_SECRET}
      PORTAINER_OIDC_CLIENT_ID: ${PORTAINER_OIDC_CLIENT_ID}
      PORTAINER_OIDC_CLIENT_SECRET: ${PORTAINER_OIDC_CLIENT_SECRET}
```

- [ ] **Step 3: Recreate server + worker so they see the new env + blueprint**

Run: `cd /home/pi/Projects/Docker/Authentik && docker compose up -d server worker`
Expected: both recreated.

- [ ] **Step 4: Trigger/verify blueprint application**

Run:
```bash
sleep 20
docker logs authentik-worker 2>&1 | grep -iE "blueprint|mvp" | tail -20
```
Expected: log lines showing the `MVP - SSO apps` blueprint discovered and applied with no errors. (Authentik re-applies file blueprints automatically; if not picked up, run `docker compose restart worker` and re-check.)

- [ ] **Step 5: Verify objects via API (using the bootstrap token)**

Run:
```bash
source /home/pi/Projects/Docker/Authentik/.env
curl -sS -H "Authorization: Bearer $AUTHENTIK_BOOTSTRAP_TOKEN" \
  https://sso.holy-grail.ch/api/v3/core/applications/ | grep -o '"slug":"[a-z]*"'
```
Expected: includes `"slug":"audiobookshelf"` and `"slug":"portainer"`.
Fallback: if the blueprint fails to apply cleanly, configure the two providers/apps/groups/bindings manually in the admin UI using the same values, then continue.

---

## Task 5 [AGENT]: Route Portainer VPN/LAN-only

**Files:** Modify `Docker/Portainer/docker-compose.yaml`; create `Docker/Traefik/traefik/dynamic/portainer.yml`.

- [ ] **Step 1: Add `traefik_proxy` to Portainer compose**

Edit `Docker/Portainer/docker-compose.yaml` so the `portainer` service joins the proxy network and uncomment the networks block:
```yaml
  portainer:
    image: portainer/portainer-ce:latest
    container_name: portainer
    environment:
      TZ: Europe/Zurich
    ports:
      - "9443:9443"   # HTTPS — LAN fallback
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - portainer_data:/data
    restart: unless-stopped
    networks:
      - traefik_proxy
# =========================================================
# Volumes =================================================
# =========================================================
volumes:
  portainer_data:
# =========================================================
# Networks ================================================
# =========================================================
networks:
  traefik_proxy:
    external: true
```

- [ ] **Step 2: Recreate Portainer**

Run: `cd /home/pi/Projects/Docker/Portainer && docker compose up -d`
Expected: `portainer` recreated, now on `traefik_proxy`.

- [ ] **Step 3: Create the internal Traefik route `Docker/Traefik/traefik/dynamic/portainer.yml`**

```yaml
http:
  routers:
    portainer:
      rule: "Host(`portainer.fastpi.homelab`)"
      entryPoints: ["internal"]
      service: portainer
      middlewares:
        - portainer-ipallowlist

  middlewares:
    portainer-ipallowlist:
      ipAllowList:
        sourceRange:
          - "127.0.0.1/32"
          - "::1/128"
          - "192.168.1.0/24"   # LAN
          - "172.24.0.0/16"    # traefik_proxy bridge — covers LAN and VPN traffic NATted by Docker

  services:
    portainer:
      loadBalancer:
        servers:
          - url: "http://portainer:9000"
        passHostHeader: true
```
Note: Portainer serves HTTP on `:9000` inside the container (Traefik terminates TLS), so the service URL uses `:9000`, not `:9443`.

- [ ] **Step 4: Verify Portainer reachable on the internal entrypoint**

Run: `curl -sS -H "Host: portainer.fastpi.homelab" -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/`
Expected: `200` or `308` (Portainer responds). A `403` means the IP allowlist rejected the source — fine from off-LAN, expected to pass from the Pi/LAN.

---

## Task 6 [USER]: Wire OIDC into the apps + create test users

Claude provides exact values (from `.env`) in chat. User enters them in each app's web UI.

- [ ] **Step 1 [USER]: Audiobookshelf** — Settings → Authentication → enable **OpenID Connect**:
  - Issuer URL: `https://sso.holy-grail.ch/application/o/audiobookshelf/` (click **Auto-populate** to fill endpoints)
  - Client ID: `audiobookshelf` · Client Secret: `ABS_OIDC_CLIENT_SECRET` (from `.env`)
  - Button text: `Login with Holy-Grail` (optional)
  - **Group Claim:** `groups`
  - Enable **Automatically create new users**; "Match existing users by" = `email`
  - Save.

- [ ] **Step 2 [USER]: Portainer** — Settings → Authentication → **OAuth**, provider **Custom**:
  - Client ID: `portainer` · Client Secret: `PORTAINER_OIDC_CLIENT_SECRET` (from `.env`)
  - Authorization URL: `https://sso.holy-grail.ch/application/o/authorize/`
  - Access token URL: `https://sso.holy-grail.ch/application/o/token/`
  - Resource URL: `https://sso.holy-grail.ch/application/o/userinfo/`
  - Redirect URL: `https://portainer.fastpi.homelab`
  - User identifier: `preferred_username` · Scopes: `openid email profile`
  - Save. (Keep "internal" admin auth enabled as a fallback.)

- [ ] **Step 3 [USER]: Create test users in Authentik** (`https://sso.holy-grail.ch/if/admin/` → Directory → Users):
  - `tomi-admin` → add to group `admin`
  - `tomi-stream` → add to group `streaming`
  - Set passwords for both.

---

## Task 7 [AGENT+USER]: Acceptance verification + bookkeeping

- [ ] **Step 1 [USER]: Streaming user test**
  Incognito → `https://audiobookshelf.holy-grail.ch` → "Login with OpenID" → log in as `tomi-stream`. Expected: logged in as a **regular user**. Then `https://sso.holy-grail.ch` → the user's app list should show **Audiobookshelf only** (no Portainer tile).

- [ ] **Step 2 [USER]: Admin user test**
  Incognito → ABS → log in as `tomi-admin`. Expected: ABS shows this account as **Admin** (from the `groups: ["admin"]` claim). Then (on LAN/VPN) `https://portainer.fastpi.homelab` → "Login with OAuth" → `tomi-admin` logs in. First time it's a normal Portainer user → in Portainer (as the built-in admin) promote `tomi-admin` to administrator. Expected: admin access.

- [ ] **Step 3 [USER]: Negative test**
  Confirm `https://portainer.holy-grail.ch` does **not** exist publicly (no Cloudflare hostname was created), and `portainer.fastpi.homelab` is unreachable when off LAN/VPN.

- [ ] **Step 4 [AGENT]: Add checklist row** in `Docker/_global/checklist.md` for `Authentik` — all `❌`, empty version/date/tag columns (per repo rules; never self-tick).

- [ ] **Step 5 [AGENT]: Commit the docs only** (plan). Leave deploy-side files (compose, routes, blueprint, `.env`) **uncommitted** for the user to commit on their cadence, per repo precedent. Print a summary of created/modified files and the exact app-side secret values for the user.

---

## Self-Review notes
- **Spec coverage:** stack (T1-2), public exposure (T3), groups+providers+apps+bindings+ABS role claim (T4), Portainer VPN/LAN route (T5), app wiring (T6), acceptance criteria 1-6 (T2,T3,T4,T7). All spec sections mapped.
- **Risk/iteration points:** Authentik 2026.5 blueprint tag/field names (`!Context`, `!Env`, `!Find` by `managed` slug, `redirect_uris` object form, default flow slugs) may need adjustment against the running version — Task 4 has an API verify + UI fallback. The bootstrap healthcheck may be slow on the Pi (Task 2 retries). Cloudflare hostname target must mirror the working ABS entry (Task 3 Step 2).
- **Secrets:** only generated locally into gitignored `.env`; `.env.example` holds placeholders.
