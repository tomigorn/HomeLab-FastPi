# Authentik

[Authentik](https://goauthentik.io/) identity provider for homelab login,
served at **https://sso.holy-grail.ch**. Built directly from the official
`docker-compose` (tag `2026.5.2`), with outbound transactional email via Brevo.
No inbound mail. Flows are configured in the Authentik web UI after first start;
applications added since then are declared as blueprints in `blueprints/` (see
[Blueprints](#blueprints)).

## Project status — last reviewed 2026-09-25

Read this first when picking the project back up. Detail lives in `SETUP.md`;
this is just where things stand.

### Working, and verified by test (not just configured)

| Area | State | How it was verified |
|---|---|---|
| IdP | live at `sso.holy-grail.ch`, 2026.5.2 | in daily use |
| Outbound mail (Brevo) | **working** | 2026-08-17: connected from `authentik-worker`, `EHLO 250`, STARTTLS offered, **SMTP AUTH succeeded**. No mail sent. |
| Brevo domain auth | in place | `brevo-code` TXT at root, DKIM at `brevo1._domainkey` + `brevo2._domainkey`, DMARC present. (`mail._domainkey` is Brevo's *old* selector and is empty — that is expected, not a fault. No root SPF: normal for Brevo's automatic flow, which uses its own return-path.) |
| Invite-only enrollment | **built and gated** | Invitation stage has `continue_flow_without_invitation=False`, so the flow refuses without a valid `itoken`. Stage order matches SETUP.md §3. |
| Mandatory MFA | enforced | TOTP at order 40 + login-flow backstop denying device-less accounts |
| Nextcloud SSO (OIDC) | **working end to end** | 2026-08-16: a real login provisioned `user_oidc` account with groups `cloud-users`, `cloud-admins`, `admin` — Nextcloud admin rights confirmed |

### Not done yet — this is the next step

**The enrollment path has still never been walked by a person.** An invitation is
issued and outstanding, and every component is configured and individually
verified, but the end-to-end path — invite link → warning page → form → Brevo
email → click → TOTP → logged in — is **unproven in practice**.

Brevo has now been shown to *send*: the admin-notification rule below delivered a
real message to `tomigorn@gmail.com` on 2026-09-25. That proves the relay accepts
and sends our mail; it still does not prove the enrollment verification mail
lands in an arbitrary inbox rather than a spam folder.

Next time, start here:

1. Admin interface → **Directory → Invitations → Create**, flow `enrollment`, set an expiry.
2. Open the link: `https://sso.holy-grail.ch/if/flow/enrollment/?itoken=<token>`
   Opening it is safe — the warning stage at order 1 means nothing is consumed
   until **Continue** is pressed.
3. Walk the whole flow through with a throwaway address.
4. New users are auto-added to `streaming-users` (and nothing else) by the
   enrollment user-write stage. Grant `cloud-users` / `cloud-admins` by hand if
   they should reach Nextcloud, or Authentik refuses them at the Nextcloud gate.

Also outstanding, unrelated to invites: give Nextcloud's local `admin` account a
long random password and enable Nextcloud's own TOTP on it — it is the one login
that bypasses this IdP (see the Nextcloud project docs).

### Known issues

1. **The default `profile` scope also emits a `groups` claim** containing every
   authentik group, so group names such as `authentik Admins` and
   `streaming-users` leak into Nextcloud as Nextcloud groups. Harmless today —
   only the literal `admin` group grants rights, and access is still gated by the
   policy binding — but two mappings emitting the same claim name is fragile: if
   the default one ever wins the merge, `admin` disappears and admin rights are
   silently lost. Fix by setting `user_oidc`'s `--group-whitelist-regex` so
   Nextcloud only provisions `cloud-*` and `admin`.

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

## Blueprints

`blueprints/` holds application config as code. They are **not** auto-applied —
the directory is not mounted into the stack. Apply one by hand:

```bash
docker cp blueprints/<name>.yaml authentik-server:/blueprints/<name>.yaml
docker exec -i authentik-server ak apply_blueprint <name>.yaml
```

`ak apply_blueprint` takes a path relative to `/blueprints`, not an absolute
one. Applying is idempotent, so re-running after an edit is safe.

> **The copied files are ephemeral — this bites on upgrade.** `docker-compose.yaml`
> mounts only `./data` and `./custom-templates`; `./blueprints` is **not** bind-mounted.
> A `docker cp` writes into the server container's writable layer, so **every file
> copied there is destroyed by `docker compose up -d --force-recreate` or any image
> bump** — including the Authentik upgrade this config was cleared for. The applied
> *state* survives, because it lives in Postgres; only the source files vanish.
> After any recreate, re-copy them. They are also absent from `authentik-worker`.
>
> Deliberately not bind-mounted: the worker runs `blueprints_discovery` hourly
> (`19 * * * *`), and `check_blueprint_v1_file()` auto-creates an enabled
> `BlueprintInstance` for any YAML it finds under `/blueprints`. Mounting the
> directory would turn these files into continuously-enforced config that silently
> overwrites changes made in the web UI — which is where most of this instance's
> config is actually managed. Manual application is the deliberate choice.

Blueprints hold **no secrets**: `client_id`/`client_secret` are generated by
Authentik on first apply and read back from the provider, never written here.

- **`enrollment-invite-warning.yaml`** — the order-1 warning page described above.

- **`enrollment-defaults-and-notify.yaml`** — two things that make an invited
  account usable and visible. It sets the enrollment user-write stage's
  `create_users_group` to **`streaming-users`** (previously unset, so an invited
  person finished sign-up and landed in *no* groups, seeing a working login with
  nothing behind it and no error explaining why), and it adds an
  `EventMatcherPolicy` + `NotificationRule` that emails the members of
  `authentik Admins` whenever a user object is created.

  Two traps recorded in that file: the matcher's **`app` field must stay null** —
  it looks like a model app-label and the API even offers `authentik.core` as a
  choice, but `passes_app()` compares it to `Event.app`, which is the *source
  module path* of whatever emitted the event, so setting it matches nothing and
  the rule simply never fires, with no error to notice. And the mail is triggered
  at account **creation** (the user-write stage), so it means "somebody redeemed
  an invite and submitted the form", not "they finished TOTP".

- **`nextcloud-oidc.yaml`** — Nextcloud SSO. Creates the `cloud-users` and
  `cloud-admins` groups, a `Nextcloud Profile` scope mapping, the OAuth2/OIDC
  provider and its application. Access control is the two policy bindings at the
  bottom of the file: only members of those groups can obtain a token, so a
  non-member is refused before Nextcloud ever sees them. `cloud-admins` members
  additionally get Nextcloud administrator rights, because the scope mapping adds
  Nextcloud's hard-coded `admin` group to the `groups` claim.

  Two things that are easy to get wrong: `grant_types` **must** be set (the UI
  wizard fills it in, a blueprint does not, and an empty list makes Authentik
  reject every authorization request as malformed), and scope mappings must be
  looked up by `name` rather than `scope_name` (two mappings share the scope
  name `email`).

### Resolved 2026-09-25 — `ak_groups` deprecation (was an upgrade blocker)

`nextcloud-oidc.yaml`'s scope mapping used `request.user.ak_groups`, deprecated
by authentik in favour of `request.user.groups`. Both calls were swapped and the
blueprint re-applied, so **upgrading authentik is no longer blocked by this.**

It was worth fixing early because of *how* it would have broken. Once authentik
removes the attribute the expression raises, the `groups` claim comes back
**empty**, login keeps working, and every user silently loses Nextcloud admin
rights and group membership — a quiet permissions regression, far worse to
diagnose than a loud failure.

Worth knowing: `user.groups` is authentik's own M2M to
`authentik.core.models.Group`, **not** Django's `contrib.auth` group relation,
despite the name — confirmed before the swap, since getting that wrong would
have produced exactly the silent empty claim described above. Output was
captured before and after and is identical.

Verify at any time that a `cloud-admins` member resolves to all three groups:

```bash
docker exec -i authentik-server ak shell -c "
from authentik.core.models import User
from authentik.providers.oauth2.models import ScopeMapping
print(ScopeMapping.objects.get(name='Nextcloud Profile').evaluate(
    user=User.objects.get(username='akadmin'), request=None))"
# expected: {'name': ..., 'groups': ['cloud-users', 'cloud-admins', 'admin']}
```

Editor note: the blueprint pins a deliberately loose local schema
(`blueprints/blueprint.schema.json`) via a modeline. Authentik's published schema
describes the resolved API shape and rejects its own `!Find`/`!KeyOf` tags; with
no schema at all, editors auto-match an unrelated one. `yaml.customTags` in
`~/.vscode/settings.json` silences the tag warnings.

### Invitation stage order — warn before the link is consumed (2026-09-25)

`InvitationStageView.dispatch()` deletes a `single_use` invitation the moment the
stage is *reached*. There is no consume-on-completion option — the same stage both
validates and consumes — so whichever stage runs first decides when the link dies.

Originally the invitation stage was first (order 5), so the invite was consumed
as soon as the flow reached that stage — before the recipient typed anything. An
accidental reload, or a link scanner that renders JavaScript (Safe Links-style
detonation), was enough, and the person was left with "Invalid invite/invite not
found".

Be precise about the mechanism, because an earlier version of this file was not:
the invite URL `/if/flow/enrollment/?itoken=…` is served by `FlowInterfaceView`,
which returns only a static JS shell and **does not touch the flow executor**. The
invitation is consumed by the browser's subsequent call to
`/api/v3/flows/executor/enrollment/?query=itoken=…`. So a plain link *prefetcher*
that only fetches the HTML does **not** burn the invite — every `invitation_used`
event on this instance has the executor path, never `/if/flow/`. The original
"measured 1 → 0 on a single curl" was a `curl` against the executor API directly,
which is not what a prefetcher does.

The fix is a static, display-only prompt stage at **order 1**, ahead of the
invitation stage, declared in `blueprints/enrollment-invite-warning.yaml`. It
tells the recipient the link is one-time and lists what to have ready (username,
a reachable email address, a 15-character password, an authenticator app). Nothing
is consumed until they press **Continue**.

    1   enrollment-invite-warning   (alert_warning + static, display only)
    5   enrollment-invitation       (validates + consumes)
    10  credentials prompt
    20  user-write (inactive)
    30  email verify
    40  TOTP setup
    100 login

Verified end to end:

| Step | Challenge returned | Invitation |
|---|---|---|
| Open the invite link (GET) | `invite_one_time_warning`, `invite_checklist` | **intact** |
| Press Continue (POST) | `username`, `name`, `password`, `email`, `password_repeat` | **consumed** |

Two things worth knowing when reading the audit log or changing this:

- **The `invitation_used` event is recorded with method `GET`.** That is not the
  link being opened — after the Continue POST the frontend fetches the next
  challenge with a GET, and the non-interactive invitation stage executes during
  that fetch. Do not read a `GET` in the event log as proof the link was consumed
  on open; check what preceded it.
- **An uninvited visitor sees the warning page before being refused**, since the
  invitation stage now runs one step later. They are still stopped before the
  signup form, so the credentials prompt and its HaveIBeenPwned password policy
  stay invite-only, and `invite.fixed_data` prefill still works because the
  invitation stage remains ahead of the credentials prompt.

To revert to consuming on open, delete the order-1 binding:

```bash
docker exec -i authentik-server ak shell -c "
from authentik.flows.models import Flow, FlowStageBinding
FlowStageBinding.objects.filter(target=Flow.objects.get(slug='enrollment'),
                                order=1).delete()"
```

## Routing

`sso.holy-grail.ch` is routed by Traefik's file provider
(`Docker/Traefik/traefik/dynamic/sso.yml`) to `http://authentik-server:9000`,
on `websecure` with a Cloudflare-resolver TLS certificate.
