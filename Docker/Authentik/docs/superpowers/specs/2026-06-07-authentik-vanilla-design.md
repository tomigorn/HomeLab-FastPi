# Authentik (vanilla) — design

**Date:** 2026-06-07
**Status:** Approved (auto-approved per user preference; flow straight to plan + execution)

## Goal

Stand up a plain, vanilla Authentik identity provider for homelab login at
`sso.holy-grail.ch`, able to send outbound transactional mail — email-address
confirmation, password reset, and registration/enrollment links — via Brevo
(or an equivalent transactional SMTP provider). Authentik connects directly to
the provider over SMTP; there is **no** self-hosted mail server.

This is a re-creation. An earlier, far more elaborate Authentik project (OIDC
pre-provisioning for Audiobookshelf/Portainer, invite-enrollment blueprints,
forward-auth middleware, a docker-socket-driven worker) was removed in commit
`2fcf170`. This rebuild deliberately keeps **only the core login stack + email**
and none of that customization — "just vanilla authentik."

## Non-goals (explicitly out of scope)

- No OIDC/SAML application pre-provisioning via blueprints.
- No enrollment / MVP blueprints or any "adjustment scripts."
- No Traefik forward-auth middleware or per-app gating wiring.
- No self-hosted mail server (no inbound mail, no mailboxes). Outbound only,
  via Brevo.
- Flows, applications, and providers are configured later by hand in the
  Authentik web UI — not part of this project.

## Architecture

Matches the upstream `goauthentik` docker-compose for tag `2026.5.2` (verified
against `https://goauthentik.io/docker-compose.yml`). Three services, no Redis
(current Authentik does not use it):

| Container | Image | Role | Networks |
|---|---|---|---|
| `authentik-postgresql` | `postgres:16-alpine` | database | `authentik_internal` |
| `authentik-server` | `ghcr.io/goauthentik/server:2026.5.2` (`command: server`) | web UI + API + embedded outpost | `authentik_internal`, `traefik_proxy` |
| `authentik-worker` | `ghcr.io/goauthentik/server:2026.5.2` (`command: worker`) | background tasks incl. sending email | `authentik_internal` |

- `authentik_internal` is a project-local bridge network (retains internet
  egress so the worker can reach Brevo's SMTP relay).
- `traefik_proxy` is the existing external network; only the server joins it so
  Traefik can route to it by container name.
- Persistence via bind mounts under the project dir: `./postgres-data`,
  `./media`, `./certs` (all gitignored).
- The worker mounts `/var/run/docker.sock` and runs as root — this is the
  **upstream-vanilla default** (used only for Docker/Kubernetes *outpost*
  orchestration, which a login-only setup does not need). Kept for fidelity to
  vanilla; documented in the README as a safe one-line removal for anyone who
  only uses the embedded outpost.

## Email (Brevo)

`AUTHENTIK_EMAIL__*` environment variables on **both** server and worker
(the worker sends the mail; both read config from env):

| Variable | Value |
|---|---|
| `AUTHENTIK_EMAIL__HOST` | `smtp-relay.brevo.com` |
| `AUTHENTIK_EMAIL__PORT` | `587` |
| `AUTHENTIK_EMAIL__USERNAME` | `${EMAIL_USERNAME}` (Brevo SMTP login) |
| `AUTHENTIK_EMAIL__PASSWORD` | `${EMAIL_PASSWORD}` (Brevo SMTP key) |
| `AUTHENTIK_EMAIL__USE_TLS` | `true` (STARTTLS on 587) |
| `AUTHENTIK_EMAIL__USE_SSL` | `false` |
| `AUTHENTIK_EMAIL__TIMEOUT` | `10` |
| `AUTHENTIK_EMAIL__FROM` | `${EMAIL_FROM}` e.g. `Authentik <no-reply@holy-grail.ch>` |

The provider is interchangeable (Resend, MailerSend, SendGrid, etc.) — only the
host/port/credentials in `.env` change. Domain authentication (SPF/DKIM/DMARC)
is done in Cloudflare DNS per the provider's instructions so mail is trusted as
`holy-grail.ch`.

## Routing

Recreate the Traefik file-provider dynamic config `sso.yml`:

- Router `authentik`: `Host(\`sso.holy-grail.ch\`)`, entryPoint `websecure`,
  TLS `certResolver: cloudflare`, middleware `authentik-secure-headers`.
- Middleware `authentik-secure-headers`: HSTS, nosniff, referrer-policy,
  `frameDeny: false` + `customFrameOptionsValue: SAMEORIGIN` (Authentik's UI
  needs same-origin framing), empty `Server` header.
- Service `authentik` → `http://authentik-server:9000`, `passHostHeader: true`.

Reached via Cloudflare Tunnel (`192.168.1.2:443`, HTTPS, No-TLS-Verify) →
Traefik → `authentik-server:9000`.

Also trim the Traefik `README.md`: its current "Authentik SSO integration"
section documents the removed forward-auth / OIDC-mode / example-route files
and dangling doc paths. Reduce it to the vanilla reality — only the public
route to Authentik itself.

## Project files (standard Docker template)

- `docker-compose.yaml` — sectioned Services / Networks / Volumes layout with
  per-service banners.
- `.env.example` — committed template; first line `COMPOSE_PROJECT_NAME=authentik`,
  then `AUTHENTIK_TAG`, PostgreSQL vars, `AUTHENTIK_SECRET_KEY`, bootstrap
  admin vars, and the Brevo `EMAIL_*` vars (placeholder/empty values).
- `.env` — real values; gitignored.
- `.gitignore` — ignores `.env`, secrets/keys/certs, and the runtime data dirs
  (`postgres-data/`, `media/`, `certs/`).
- `README.md` — what it is + the manual steps below.

## Manual steps (documented, not automated)

These require the user's accounts/dashboards and secrets; they are written into
the README, not scripted:

1. **Cloudflare Tunnel** (Zero Trust → Tunnels → Public Hostnames): add
   `sso.holy-grail.ch` → `https://192.168.1.2:443` (No-TLS-Verify), unless an
   existing wildcard already covers it. Cloudflare creates the DNS record.
2. **Brevo**: create account → authenticate `holy-grail.ch` (add the SPF/DKIM/
   DMARC records into Cloudflare DNS) → generate an SMTP key.
3. **Fill `.env`**: `PG_PASS`, `AUTHENTIK_SECRET_KEY` (`openssl rand -base64 60`),
   `AUTHENTIK_BOOTSTRAP_PASSWORD`/`_TOKEN`/`_EMAIL`, and the Brevo `EMAIL_*`
   credentials.
4. `docker compose up -d`; first login as `akadmin` with the bootstrap password.
   Verify mail via Authentik's per-stage "Send test email" / a password-reset.

## Checklist

Add an `Authentik` row to `_global/checklist.md`: all `❌`, empty Image/Tag,
date, and Tag columns (per the rule that Claude never sets ✅ or fills version
columns on its own).

## Commits

Use `Authentik: <description>` prefix, no AI co-author trailer.
