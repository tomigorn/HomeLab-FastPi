# Authentik

[Authentik](https://goauthentik.io/) identity provider for homelab login,
served at **https://sso.holy-grail.ch**. Built directly from the official
`docker-compose` (tag `2026.5.2`), with outbound transactional email via Brevo.
No inbound mail, no pre-provisioned apps/blueprints — applications and flows are
configured in the Authentik web UI after first start.

## Stack

- `authentik-postgresql` — PostgreSQL 16 (data in the `database` named volume)
- `authentik-server` — web UI + API (joined to `traefik_proxy` for ingress)
- `authentik-worker` — background tasks, including sending email

No Redis (current Authentik does not require it). All `AUTHENTIK_*` / `PG_*`
config — including the email settings — is read from `.env` via `env_file`.

How it fits together:

```
Cloudflare (DNS + TLS) ──tunnel──> Traefik ──http──> authentik-server:9000
                                   (sso.holy-grail.ch, Cloudflare cert)
authentik-worker ──SMTP 587 (STARTTLS)──> Brevo ──> recipient inbox
```

> **Security note — Docker socket:** the worker mounts `/var/run/docker.sock`
> and runs as root. This is the upstream-vanilla default, used only to
> orchestrate Docker/Kubernetes *outposts*. A login-only install uses the
> embedded outpost and does not need it; to drop the attack surface, remove the
> `user: root` line and the docker.sock volume from the `worker` service.

## First-time setup

1. **Shared proxy network** (once, if it does not already exist):
   ```bash
   docker network create --subnet 172.24.0.0/16 traefik_proxy
   ```

2. **Cloudflare Tunnel** — Zero Trust → Networks → Tunnels → your tunnel →
   Public Hostnames: add `sso.holy-grail.ch` → `https://192.168.1.2:443` with
   **No TLS Verify** (unless a `*.holy-grail.ch` wildcard already routes to
   Traefik). Cloudflare creates the DNS record automatically. The public TLS
   certificate for `sso.holy-grail.ch` is issued by Traefik via the Cloudflare
   DNS-01 resolver (see `Docker/Traefik/traefik/dynamic/sso.yml`).

3. **Brevo (email)** — create a free Brevo account, then:
   - **Authenticate the domain (automatic — recommended):** Brevo → *Senders,
     Domains & Dedicated IPs → Domains* → add `holy-grail.ch` → choose
     **"Authenticate the domain automatically"** → Continue. In the pop-up, Brevo
     detects the DNS provider (Cloudflare); **log in to Cloudflare and click
     Allow/Authorize** — Brevo then **creates the DNS records itself** (Brevo
     code, DKIM, DMARC). No manual copy-paste. Re-check via *View Configuration →
     Authenticate this email domain* (can take up to ~48h, usually minutes).
     *(Manual fallback: if it can't auto-detect, Brevo lists the records to add by
     hand under Cloudflare → DNS → Records.)*
   - **SMTP key:** Brevo → *SMTP & API → SMTP* → copy the **Login** and generate
     an **SMTP key**; these become `AUTHENTIK_EMAIL__USERNAME` /
     `AUTHENTIK_EMAIL__PASSWORD`.
   - Any equivalent provider (Resend, MailerSend, Scaleway TEM…) works — just
     change `AUTHENTIK_EMAIL__*`.

4. **Secrets** — copy the template and fill it in:
   ```bash
   cp .env.example .env
   #   PG_PASS               openssl rand -base64 36 | tr -d '\n'
   #   AUTHENTIK_SECRET_KEY  openssl rand -base64 60 | tr -d '\n'
   #   AUTHENTIK_EMAIL__USERNAME / AUTHENTIK_EMAIL__PASSWORD  (Brevo SMTP key)
   ```

5. **Start it:**
   ```bash
   docker compose up -d
   ```

6. **Create the admin** — browse to
   `https://sso.holy-grail.ch/if/flow/initial-setup/` and set the password for
   the `akadmin` user (the default superuser).

7. **Verify email** — in the Authentik admin UI, edit the built-in email stage
   (or trigger a password-reset / enrollment flow) and confirm a message
   arrives. Configure flows for email-address confirmation, password reset, and
   registration links from there.

## Routing

`sso.holy-grail.ch` is routed by Traefik's file provider
(`Docker/Traefik/traefik/dynamic/sso.yml`) to `http://authentik-server:9000`,
on `websecure` with a Cloudflare-resolver TLS certificate.
