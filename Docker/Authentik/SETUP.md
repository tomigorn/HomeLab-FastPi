# Authentik — Setup & Architecture

Homelab identity provider (IdP / SSO) served at **https://sso.holy-grail.ch**.
This document explains how the three moving parts fit together:

1. **Mail** — outbound email via a transactional provider (Brevo)
2. **Cloudflare** — DNS, TLS, and the tunnel that exposes Authentik
3. **User account creation** — the invite-only enrollment + login + recovery flows

> `README.md` is the short quick-start. This file is the "why & how" explainer.
> The running configuration (flows/stages/policies) lives in Authentik's
> Postgres DB, **not** in git — see [Operations](#4-operations) for the snapshot
> and backup story.

```
                     ┌── Cloudflare (DNS + TLS + Tunnel) ──┐
   user browser ───► │  sso.holy-grail.ch                  │
                     └──────────────┬──────────────────────┘
                                    │  Cloudflare Tunnel (cloudflared)
                                    ▼
                         Traefik  (192.168.1.2:443, TLS)
                                    │  http://authentik-server:9000
                                    ▼
        ┌──────────── Authentik (Docker) ────────────┐
        │  server  ·  worker  ·  postgresql          │
        └───────────────────┬────────────────────────┘
                            │  SMTP 587 (STARTTLS)
                            ▼
                   Brevo  ──►  recipient inbox
```

---

## 1. Mail — why it's split out, and how it works

### Why a transactional provider instead of self-hosting mail
Authentik must send real email (email verification, password recovery, invites)
to real inboxes (Gmail, etc.). Sending mail *directly* from this Pi does **not**
work reliably:

- Home ISPs (and most clouds) **block outbound port 25**, the port mail servers
  use to deliver directly to recipients.
- A residential IP has no sending reputation, so mail is rejected or spam-foldered.
- Proper deliverability needs SPF/DKIM/DMARC **and** a reverse-DNS (PTR) record
  you can't set on a home connection.

So mail is **split out** to a transactional email provider (**Brevo**). Authentik
talks SMTP to Brevo; Brevo, an authenticated sender for `holy-grail.ch`, does the
actual delivery. There is **no** self-hosted mail server and **no** inbound mail.
(Any equivalent provider — Scaleway TEM, Mailpro, Resend… — works by changing the
`AUTHENTIK_EMAIL__*` values.)

### One-time Brevo setup
1. Create a Brevo account.
2. **Authenticate the domain — automatic (recommended, this is how it was set up):**
   Brevo → *Senders, Domains & Dedicated IPs → Domains* → add `holy-grail.ch` →
   choose **"Authenticate the domain automatically"** → Continue. A pop-up detects
   your DNS provider (Cloudflare); **log in to Cloudflare and click Allow/Authorize**.
   Brevo then **creates all required DNS records for you** (Brevo code, DKIM, DMARC) —
   no manual copy-paste. Verification can take up to ~48h (usually minutes); re-check
   with *View Configuration → Authenticate this email domain*.
   - *Manual fallback* (only if auto-detect/authorize fails): Brevo lists the records
     — a `brevo-code` TXT, two `brevo1/brevo2._domainkey` DKIM records, an SPF
     `include:spf.brevo.com`, and an optional `_dmarc` TXT — to add by hand under
     Cloudflare → DNS → Records (DNS-only / grey-cloud).
3. **SMTP credentials:** Brevo → *SMTP & API → SMTP* → note the **Login** and
   generate an **SMTP key** (this is the password).

### How Authentik is wired to it
All config is read from `.env` via `env_file:` in `docker-compose.yaml`. The
relevant variables:

```ini
AUTHENTIK_EMAIL__HOST=smtp-relay.brevo.com
AUTHENTIK_EMAIL__PORT=587
AUTHENTIK_EMAIL__USERNAME=<Brevo SMTP login>
AUTHENTIK_EMAIL__PASSWORD=<Brevo SMTP key>
AUTHENTIK_EMAIL__USE_TLS=true        # STARTTLS on 587
AUTHENTIK_EMAIL__USE_SSL=false
AUTHENTIK_EMAIL__TIMEOUT=10
AUTHENTIK_EMAIL__FROM=Holy Grail <no-reply@holy-grail.ch>
```

- The `FROM` uses the `Name <address>` form so the sender shows as **"Holy Grail"**
  instead of "no-reply". The address must stay on the authenticated domain.
- The **worker** container sends the mail. All Authentik email stages are set to
  *Use global connection settings*, so they reuse the above automatically.

### Test it
```bash
docker compose exec worker ak test_email you@example.com
```
A success line + an entry in **Brevo → Transactional → Logs** confirms it works.
Errors print directly (e.g. `535 auth failed` = bad SMTP key; sender-not-valid =
finish the Brevo domain authentication).

---

## 2. Cloudflare — DNS, TLS, and the tunnel

The domain `holy-grail.ch` is managed on Cloudflare. Authentik is reached **only**
through Cloudflare; nothing is exposed directly to the internet.

### TLS certificate
Traefik obtains the certificate for `sso.holy-grail.ch` using the **Cloudflare
DNS-01 resolver** (`certResolver: cloudflare`), the same as the other homelab
services. No manual certs.

### The tunnel (how the request reaches the Pi)
A **Cloudflare Tunnel** (the `cloudflared` container) connects the Pi outward to
Cloudflare — no inbound ports are opened on the router.

In **Cloudflare Zero Trust → Networks → Tunnels → (your tunnel) → Public Hostnames**:

| Field | Value |
|---|---|
| Subdomain / Domain | `sso` / `holy-grail.ch` |
| Service | `HTTPS` → `192.168.1.2:443` |
| TLS → **No TLS Verify** | **ON** |

Cloudflare auto-creates the DNS record for `sso`. `192.168.1.2` is the Pi, where
Traefik listens on 443.

### Traefik route
`Docker/Traefik/traefik/dynamic/sso.yml` routes the hostname to Authentik:

- `Host(\`sso.holy-grail.ch\`)` on the `websecure` entrypoint, Cloudflare cert.
- Backend: `http://authentik-server:9000` (Traefik reaches the container by name
  over the external `traefik_proxy` network).
- Plus the shared rate-limit and a secure-headers middleware (`SAMEORIGIN` framing
  so Authentik's UI works).

**Full request path:** browser → Cloudflare (DNS + edge TLS) → Tunnel → Traefik
(`192.168.1.2:443`, re-TLS via Cloudflare cert) → `authentik-server:9000`.

---

## 3. User account creation workflow

Account creation is **invite-only**. There is no public sign-up; a person can only
register if you issue them an invitation link. (Google/social login was evaluated
and deliberately **not** used — it can't be cleanly gated to invites.)

### Issuing an invite
**Admin interface → Directory → Invitations → Create:**
- **Flow:** `Create your account` (the enrollment flow)
- **Single use:** ✓ (one account per link)
- Set an expiry, then **expand the row → copy the link**:
  `https://sso.holy-grail.ch/if/flow/enrollment/?itoken=<token>`

Send that link to the person. Without a valid `itoken` the flow refuses (the
Invitation stage has *Continue flow without invitation* off).

### The enrollment flow (`enrollment`), in order
| Order | Stage | What it does |
|---|---|---|
| 5 | Invitation | requires a valid invite token (gate) |
| 10 | Prompt | collects **username, name, email, password, password-repeat** — validated by the **`enrollment-password-policy`** |
| 20 | User Write | creates the account **inactive** |
| 30 | Email | sends a verification link via Brevo; **activates the account** when clicked |
| 40 | TOTP Setup | the user scans a QR / enrolls an authenticator (MFA) |
| 100 | User Login | logs the new user in |

**What the user experiences:** open invite link → fill the form → "check your
email" → click the Brevo link (account activates) → set up their authenticator
(2FA) → logged in.

**Password policy** (`enrollment-password-policy`): minimum **15 characters**,
1 each of upper/lower/digit/symbol, rejected if found in **HaveIBeenPwned**, and
a **zxcvbn** strength check. The same policy is reused on password reset.

**MFA is mandatory.** Note on ordering: the TOTP step is currently at order **40,
after** the activating Email stage (30). MFA is still enforced because the **login
flow** denies device-less access (see backstop below) — but if you want the
stronger guarantee that *an account can never be active without MFA*, move the
TOTP binding to order **25** (before the Email stage). Then abandoning MFA leaves
the account inactive/unusable.

### Login (`default-authentication-flow`)
| Order | Stage |
|---|---|
| 10 | Identification (username/email) |
| 20 | Password |
| 30 | MFA validation — **`not_configured_action = configure`** |
| 100 | User Login |

The **MFA backstop** at step 30: any **active** user without an enrolled
authenticator is **forced to set one up at login** before proceeding. This is what
makes MFA unconditional, and it's also how a re-enrolled user (after a lost device)
gets a new TOTP.

### Password recovery (`default-recovery-flow`)
Self-service "**Forgot password?**" (on the login page) and the admin
"**Email recovery link**" button (Directory → Users → a user) both use this flow:

| Order | Stage |
|---|---|
| 10 | Identification (auto-skipped for admin-generated links) |
| 20 | Email — sends the reset link via Brevo |
| 21 | MFA validation — **must pass the existing TOTP** |
| 30 | Prompt — new password ×2 (same `enrollment-password-policy`) |
| 40 | User Write — saves it (never creates a user) |
| 100 | User Login |

It is wired in via **System → Brands → (default brand) → Recovery flow =
Default recovery flow**, which enables both the login-page link and the admin button.

### Lost 2FA
Because recovery *requires* the existing TOTP, a genuinely lost device can't
self-recover (by design). To help someone:
1. **Directory → Users → (user) → MFA Authenticators → Delete** their device.
2. They log in → the **MFA backstop forces them to enroll a fresh TOTP**.

### Changing a user's email
Self-service email change is **blocked by Authentik on purpose** ("Not allowed to
change email address") — it would let someone bypass the verified-email guarantee.
Change emails as an admin: **Directory → Users → (user) → Edit → Email**.

---

## 4. Operations

### Config snapshot to git
The flow/stage/policy configuration lives in the Postgres DB. To capture a
readable, version-controlled snapshot:
```bash
./export-config.sh          # writes authentik-config-export.yaml
git add authentik-config-export.yaml && git commit -m "Authentik: refresh config snapshot"
```
The snapshot contains **no secrets** (no passwords, MFA secrets, cert keys, or SMTP
creds). It's a record/restore-artifact, **not** auto-applied.

### Backups (full disaster recovery)
The git snapshot is config-only. To restore *everything* (users, their MFA devices,
sessions, certificates) you must back up:
- the **`authentik_database`** Docker volume (Postgres data), and
- the **`.env`** file (secret key + SMTP creds; gitignored).

### Locked out? (admin recovery)
With shell access you're never truly locked out. Open Authentik's Django shell and
fix a user via the ORM, e.g. re-grant superuser or reset a password:
```bash
docker compose exec server ak shell
```
```python
from authentik.core.models import User, Group
u = User.objects.get(username="akadmin")
u.ak_groups.add(Group.objects.filter(is_superuser=True).first())  # restore admin
u.set_password("a-new-password"); u.save()                          # reset password
# remove a stuck MFA device:
# from authentik.stages.authenticator_totp.models import TOTPDevice
# TOTPDevice.objects.filter(user=u).delete()
```
You can also promote any working account to admin from here and fix the rest in the UI.

### Updating Authentik
The image tag is pinned in `.env` (`AUTHENTIK_TAG`). Bump it deliberately and run
`docker compose up -d`; don't auto-update an IdP.
