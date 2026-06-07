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
