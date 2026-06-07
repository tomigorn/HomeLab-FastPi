# Authentik (vanilla) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recreate a plain, vanilla Authentik IdP at `sso.holy-grail.ch` (login + outbound email via Brevo SMTP), following the standard Docker project template, with the Traefik route and stale references cleaned up.

**Architecture:** Three-service upstream-vanilla stack (`postgresql` + `server` + `worker`, no Redis) on a project-local bridge network; the server also joins the external `traefik_proxy` network. Traefik file-provider routes `sso.holy-grail.ch` to `authentik-server:9000`. Email is sent directly to Brevo's SMTP relay via `AUTHENTIK_EMAIL__*` env vars — no mail-server container.

**Tech Stack:** Docker Compose, `ghcr.io/goauthentik/server:2026.5.2`, `postgres:16-alpine`, Traefik (file provider), Cloudflare Tunnel + DNS, Brevo transactional SMTP.

This is config-only work. There is no application code and no unit-test suite; "tests" are `docker compose config` validation and YAML parsing.

All paths are relative to the git root `/home/pi/Projects` unless absolute.

---

### Task 1: Authentik docker-compose.yaml

**Files:**
- Create: `Docker/Authentik/docker-compose.yaml`

- [ ] **Step 1: Write the compose file**

Create `Docker/Authentik/docker-compose.yaml` with exactly:

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
    mem_limit: 512m
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
    mem_limit: 1g
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
      AUTHENTIK_EMAIL__HOST: ${EMAIL_HOST}
      AUTHENTIK_EMAIL__PORT: ${EMAIL_PORT}
      AUTHENTIK_EMAIL__USERNAME: ${EMAIL_USERNAME}
      AUTHENTIK_EMAIL__PASSWORD: ${EMAIL_PASSWORD}
      AUTHENTIK_EMAIL__USE_TLS: ${EMAIL_USE_TLS}
      AUTHENTIK_EMAIL__USE_SSL: ${EMAIL_USE_SSL}
      AUTHENTIK_EMAIL__TIMEOUT: ${EMAIL_TIMEOUT}
      AUTHENTIK_EMAIL__FROM: ${EMAIL_FROM}
    volumes:
      - ./media:/media
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
    mem_limit: 1g
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
      AUTHENTIK_EMAIL__HOST: ${EMAIL_HOST}
      AUTHENTIK_EMAIL__PORT: ${EMAIL_PORT}
      AUTHENTIK_EMAIL__USERNAME: ${EMAIL_USERNAME}
      AUTHENTIK_EMAIL__PASSWORD: ${EMAIL_PASSWORD}
      AUTHENTIK_EMAIL__USE_TLS: ${EMAIL_USE_TLS}
      AUTHENTIK_EMAIL__USE_SSL: ${EMAIL_USE_SSL}
      AUTHENTIK_EMAIL__TIMEOUT: ${EMAIL_TIMEOUT}
      AUTHENTIK_EMAIL__FROM: ${EMAIL_FROM}
    user: root
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./media:/media
      - ./certs:/certs
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

- [ ] **Step 2: Validate (deferred to Task 7)**

The compose can only be rendered once `.env.example` exists (Task 2). Full validation happens in Task 7. For now just confirm the file was written.

- [ ] **Step 3: Commit**

```bash
cd /home/pi/Projects
git add Docker/Authentik/docker-compose.yaml
git commit -m "Authentik: add vanilla compose stack (server, worker, postgres)"
```

---

### Task 2: .env.example

**Files:**
- Create: `Docker/Authentik/.env.example`

- [ ] **Step 1: Write the env template**

Create `Docker/Authentik/.env.example` with exactly:

```bash
COMPOSE_PROJECT_NAME=authentik

# --- Authentik image ---
AUTHENTIK_TAG=2026.5.2

# --- PostgreSQL ---
PG_USER=authentik
PG_DB=authentik
PG_PASS=

# --- Authentik core ---
# Generate with: openssl rand -base64 60
AUTHENTIK_SECRET_KEY=
# Initial superuser (akadmin) credentials, applied on first start.
# Generate the token with: openssl rand -hex 32
AUTHENTIK_BOOTSTRAP_PASSWORD=
AUTHENTIK_BOOTSTRAP_TOKEN=
AUTHENTIK_BOOTSTRAP_EMAIL=admin@holy-grail.ch

# --- Outbound email (Brevo transactional SMTP; provider is interchangeable) ---
# USERNAME/PASSWORD come from your Brevo SMTP key. FROM address must be on a
# domain you have authenticated (SPF/DKIM) in your provider + Cloudflare DNS.
EMAIL_HOST=smtp-relay.brevo.com
EMAIL_PORT=587
EMAIL_USERNAME=
EMAIL_PASSWORD=
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false
EMAIL_TIMEOUT=10
EMAIL_FROM=Authentik <no-reply@holy-grail.ch>
```

- [ ] **Step 2: Verify every compose variable is present**

Run:
```bash
cd /home/pi/Projects/Docker/Authentik
comm -23 \
  <(grep -oP '(?<!\$)\$\{[A-Z_]+\}' docker-compose.yaml | tr -d '${}' | sort -u) \
  <(grep -oE '^[A-Z_]+=' .env.example | tr -d '=' | sort -u)
```
Expected: **no output** (every `${VAR}` used in the compose has a line in `.env.example`). The `(?<!\$)` lookbehind skips the escaped `$${POSTGRES_*}` healthcheck refs, which are container-internal and intentionally not in `.env.example`.

- [ ] **Step 3: Commit**

```bash
cd /home/pi/Projects
git add Docker/Authentik/.env.example
git commit -m "Authentik: add .env.example template (core + Brevo email vars)"
```

---

### Task 3: .gitignore

**Files:**
- Create: `Docker/Authentik/.gitignore`

- [ ] **Step 1: Write the gitignore**

Create `Docker/Authentik/.gitignore` with exactly:

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
credentials.json
auth.json

# Logs (may leak sensitive data)
*.log

# Authentik runtime data (bind mounts)
postgres-data/
media/
certs/
```

- [ ] **Step 2: Verify .env would be ignored**

Run:
```bash
cd /home/pi/Projects/Docker/Authentik
git check-ignore -v .env postgres-data/ media/ certs/
```
Expected: each path prints a matching `.gitignore` rule (i.e. all are ignored).

- [ ] **Step 3: Commit**

```bash
cd /home/pi/Projects
git add Docker/Authentik/.gitignore
git commit -m "Authentik: add .gitignore (secrets + runtime data dirs)"
```

---

### Task 4: README.md

**Files:**
- Create: `Docker/Authentik/README.md`

- [ ] **Step 1: Write the README**

Create `Docker/Authentik/README.md` with exactly:

```markdown
# Authentik

Vanilla [Authentik](https://goauthentik.io/) identity provider for homelab
login, served at **https://sso.holy-grail.ch**. Login + outbound transactional
email only — no pre-provisioned apps, blueprints, or forward-auth. Configure
flows, applications, and providers in the Authentik web UI after first start.

## Stack

- `authentik-postgresql` — PostgreSQL 16 (database)
- `authentik-server` — web UI + API (joined to `traefik_proxy`)
- `authentik-worker` — background tasks, including sending email

No Redis (current Authentik does not require it). Mail is sent straight to a
transactional SMTP provider (Brevo by default); there is no mail-server
container and no inbound mail.

> **Security note — Docker socket:** the worker mounts `/var/run/docker.sock`
> and runs as root. This is the upstream-vanilla default and is only used for
> orchestrating Docker/Kubernetes *outposts*. A login-only install uses the
> embedded outpost and does not need it — to drop the attack surface, remove the
> `user: root` line and the `/var/run/docker.sock:/var/run/docker.sock` volume
> from the `worker` service.

## First-time setup

1. **Create the shared proxy network** (once, if it does not exist):
   ```bash
   docker network create --subnet 172.24.0.0/16 traefik_proxy
   ```

2. **Cloudflare Tunnel** — in Zero Trust → Networks → Tunnels → your tunnel →
   Public Hostnames, add `sso.holy-grail.ch` → `https://192.168.1.2:443` with
   **No TLS Verify** enabled (unless a `*.holy-grail.ch` wildcard already
   routes to Traefik). Cloudflare creates the DNS record automatically.

3. **Email provider (Brevo)** — create a free Brevo account, authenticate the
   `holy-grail.ch` domain, and add the SPF/DKIM/DMARC records it provides into
   Cloudflare DNS. Generate an SMTP key (used as `EMAIL_USERNAME` /
   `EMAIL_PASSWORD`). Any equivalent provider (Resend, MailerSend, SendGrid…)
   works — just change the `EMAIL_*` values.

4. **Configure secrets:**
   ```bash
   cp .env.example .env
   # then edit .env and fill in:
   #   PG_PASS                      (any strong random string)
   #   AUTHENTIK_SECRET_KEY         openssl rand -base64 60
   #   AUTHENTIK_BOOTSTRAP_PASSWORD (initial akadmin password)
   #   AUTHENTIK_BOOTSTRAP_TOKEN    openssl rand -hex 32
   #   EMAIL_USERNAME / EMAIL_PASSWORD (Brevo SMTP key)
   ```

5. **Start it:**
   ```bash
   docker compose up -d
   ```

6. **Log in** at https://sso.holy-grail.ch with user `akadmin` and the bootstrap
   password. To verify mail, trigger a password reset or use a flow's
   "Send test email" action and confirm delivery.

## Routing

Traefik routes `sso.holy-grail.ch` → `authentik-server:9000` via the file
provider config `Docker/Traefik/traefik/dynamic/sso.yml`. Path: Cloudflare
Tunnel → Traefik (`websecure`, Cloudflare TLS cert) → Authentik.
```

- [ ] **Step 2: Commit**

```bash
cd /home/pi/Projects
git add Docker/Authentik/README.md
git commit -m "Authentik: add README (setup, Brevo email, security note)"
```

---

### Task 5: Traefik dynamic route (sso.yml)

**Files:**
- Create: `Docker/Traefik/traefik/dynamic/sso.yml`

- [ ] **Step 1: Write the route file**

Create `Docker/Traefik/traefik/dynamic/sso.yml` with exactly:

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

- [ ] **Step 2: Verify it is valid YAML**

Run:
```bash
python3 -c "import yaml; yaml.safe_load(open('/home/pi/Projects/Docker/Traefik/traefik/dynamic/sso.yml')); print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
cd /home/pi/Projects
git add Docker/Traefik/traefik/dynamic/sso.yml
git commit -m "Traefik: add sso.holy-grail.ch route to Authentik server"
```

---

### Task 6: Trim Traefik README's stale Authentik section

The Traefik `README.md` still documents the removed forward-auth / OIDC-mode /
example-route files and dead doc paths. Replace that whole section with the
vanilla reality.

**Files:**
- Modify: `Docker/Traefik/README.md`

- [ ] **Step 1: Read the file**

Read `Docker/Traefik/README.md`. The section to replace begins at the line
`## Authentik SSO integration` and runs to the **end of the file**.

- [ ] **Step 2: Replace the section**

Use Edit to replace everything from `## Authentik SSO integration` through the
end of the file with exactly:

```markdown
## Authentik SSO integration

[Authentik](../Authentik/README.md) is the homelab IdP, reached at
`sso.holy-grail.ch`.

`dynamic/sso.yml` routes `sso.holy-grail.ch` (websecure) →
`authentik-server:9000` — the Authentik login UI and API, reached via
Cloudflare Tunnel (`192.168.1.2:443`, HTTPS, No-TLS-Verify) → Traefik → here.

This is a vanilla Authentik install (login + outbound email only). There is no
forward-auth middleware and no pre-provisioned OIDC wiring in Traefik; apps that
use Authentik are configured directly in the Authentik web UI.
```

- [ ] **Step 3: Verify no dangling references remain**

Run:
```bash
cd /home/pi/Projects/Docker/Traefik
grep -nE 'forwardauth|forward-auth|auth-integration-modes|_example-routes|Mode 1|Mode 2' README.md || echo "clean"
```
Expected: `clean`

- [ ] **Step 4: Commit**

```bash
cd /home/pi/Projects
git add Docker/Traefik/README.md
git commit -m "Traefik: trim Authentik README section to vanilla public route"
```

---

### Task 7: Validate the full compose + add checklist row

**Files:**
- Modify: `Docker/_global/checklist.md`

- [ ] **Step 1: Render and validate the compose**

This validates compose syntax and that every `${VAR}` resolves, using the
example env (no real `.env` needed):

```bash
cd /home/pi/Projects/Docker/Authentik
docker compose --env-file .env.example config -q && echo "compose OK"
```
Expected: `compose OK` with no errors. (A warning that the external network
`traefik_proxy` is not found is acceptable — `config` does not check network
existence; ignore it if it appears.)

- [ ] **Step 2: Add the checklist row**

In `Docker/_global/checklist.md`, add this row to the table (after the last
existing data row). All `❌`, every other column empty — per the rule that
Claude never sets ✅ or fills the version/date/tag columns on its own:

```markdown
| Authentik | ❌ | ❌ | | |  |
```

- [ ] **Step 3: Verify the row is present**

Run:
```bash
grep -n '^| Authentik |' /home/pi/Projects/Docker/_global/checklist.md
```
Expected: one matching line showing `❌ | ❌` and empty trailing columns.

- [ ] **Step 4: Commit**

```bash
cd /home/pi/Projects
git add Docker/_global/checklist.md
git commit -m "Authentik: add project row to review checklist"
```

---

## Done / handoff

After all tasks, the repo contains a complete vanilla Authentik project and its
Traefik route. The remaining steps are **user-side and cannot be automated**
(they need the user's Brevo account, Cloudflare dashboard, and secrets):

1. Add the `sso.holy-grail.ch` Public Hostname in the Cloudflare Tunnel.
2. Sign up for Brevo, authenticate `holy-grail.ch` (SPF/DKIM/DMARC in
   Cloudflare DNS), get an SMTP key.
3. `cp .env.example .env` and fill in the secrets.
4. `docker compose up -d`, log in as `akadmin`, verify a password-reset email.
