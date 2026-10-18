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
real message to the admin address on 2026-09-25. That proves the relay accepts
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

### Closed, unresolved — Audiobookshelf OIDC "login twice" (2026-09-25)

Recorded because it cost a long investigation, not because it is open. Do not
re-chase it unless it happens to a **new invitee on a cold login**.

Symptom: first "Login with Holy Grail" returned to Audiobookshelf logged out; a
second click worked immediately without re-authenticating at authentik.

It did **not reproduce**. A deliberate re-test — account deleted from both
authentik and Audiobookshelf, enrolled fresh, then logged in — auto-registered a
brand-new account and logged in on the **first** click in 4.1 seconds.

Two hypotheses, both unconfirmed:

1. `auth_cb` expiry. Audiobookshelf sets that cookie with `maxAge: TWO_MINUTES`
   (`Auth.js`, `paramsToCookies`) before redirecting to the IdP, and returns a
   bare `400 "No callback or already expired"` if it is gone at callback time.
   A first login means typing a password *and* a TOTP code, which can exceed two
   minutes. The second attempt is fast because authentik already has a session.
   The constant is hardcoded — not configurable.
2. **Most likely:** stale browser cookies. The failure happened minutes after the
   old June `testuser` was deleted out from under an open Audiobookshelf tab. The
   browser still held a `refresh_token` cookie for a user that no longer existed,
   `/auth/refresh` 401'd (`Failed to refresh token`), and the client fell back to
   the login page. Clicking again replaced the cookies. If so it was collateral
   from the deletion, not a defect, and invitees arriving clean never hit it.

Ruled out along the way: stale `auth_method` (overwritten unconditionally on every
login start), first-login auto-registration (proven fine by the re-test), and a
missing `X-Forwarded-Proto` (the logged `redirect_uri` is correctly `https://`).

Note for any future dig: two of the three failure paths (`No callback or already
expired`, `No session`) write **no log line at all**, which is why the original
failure left no trace. Only the passport-error path logs, and it redirects to
`/login?error=...`.

## Admin SSO (homelab-admins)

Six admin tools sit behind Authentik: Traefik dashboard, Grafana, Portainer,
AdGuard Home, wg-easy and Home Assistant. Access to each is an Authentik
Application group binding to `homelab-admins` (an application with a binding is
denied to everyone the bindings don't pass). All six hostnames are reachable from
LAN and VPN only, via the `local-networks@file` Traefik middleware. The whole
setup is config as code in `scripts/provision-admin-sso.py`; the design is in
`docs/superpowers/specs/2026-10-18-homelab-admin-sso-design.md`.

| Tool | URL | Method | Break-glass |
|---|---|---|---|
| Traefik dashboard | https://traefik.holy-grail.ch | forward auth (`authentik@file`) | none over the network (basicAuth router removed 2026-10-19). Shell: `docker logs traefik`, the access log, or drop a temporary router file into `Traefik/traefik/dynamic/` (watched, no restart) |
| Grafana | https://grafana.holy-grail.ch | native generic OAuth (role `GrafanaAdmin` from groups) | login form + Basic auth disabled, port `127.0.0.1:3001`. Shell: set `GF_AUTH_DISABLE_LOGIN_FORM=false` in `grafana/docker-compose.yaml`, `docker compose up -d`, `ssh -L 3001:127.0.0.1:3001 fastpi`, log in at `http://localhost:3001/login?disableAutoLogin=true`, set it back; lost password: `docker exec grafana grafana cli admin reset-admin-password <pw>` |
| Portainer | https://portainer.holy-grail.ch | native OAuth (CE "Custom"; user `tomigorn` pre-created as admin, auto-provisioning off) | `POST /api/auth` refused by Traefik (router `portainer-password-login-block`), port `127.0.0.1:9443`. Shell: `ssh -L 9443:127.0.0.1:9443 fastpi`, then `https://localhost:9443/#!/internal-auth` as the initial admin; lost password: stop the container, `docker run --rm -v docker_portainer_data:/data portainer/helper-reset-password` |
| AdGuard Home | https://adguard.holy-grail.ch | forward auth; Authentik injects HTTP Basic for AdGuard user `authentik-proxy` (middleware `authentik-basic@file`; credentials in `homelab-admins` group attributes `adguard_username` / `adguard_password`) | no human user (only `authentik-proxy`). Shell: add a user (bcrypt hash) under `users:` in `adguard/conf/AdGuardHome.yaml` with the container stopped, start it, `ssh -L 3000:127.0.0.1:3000 fastpi`; steps in `adguard/docker-compose.yaml` |
| wg-easy | https://wg-easy.holy-grail.ch | native OIDC (custom `email_verified` scope mapping; admin linked by email) | password login disabled (`DISABLE_PASSWORD_AUTH=true`). Shell: set it to `false` in `WireguardVPN/docker-compose.yaml`, `docker compose up -d`, log in at `/login?auto_launch=false`, set it back; lost password: `docker exec -it WireGuard-VPN cli db:admin:reset` |
| Home Assistant | https://ha.holy-grail.ch | `hass-oidc-auth` 1.2.1 (public client) | owner account at `/?skip_oidc_redirect=true` (also on `http://192.168.1.2:8123`) |

### Re-running the provisioning

```bash
cd Docker/Authentik
docker compose exec -T server ak shell < scripts/provision-admin-sso.py | python3 scripts/apply-sso-env.py
```

The script is idempotent. Secrets never touch the terminal or git: the script
emits `ENV <dir>/.env KEY=value` lines and `apply-sso-env.py` writes them into the
gitignored `.env` files, printing key names only. The AdGuard proxy password is
only set when you pass it in (`docker compose exec -T -e ADGUARD_PROXY_PASSWORD server ak shell ...`),
i.e. when rotating it; otherwise the stored attributes are left untouched.

To add a new app, add a block to `provision-admin-sso.py` using the helpers:

- `oidc(name, redirects, ...)` creates the OIDC provider (client id/secret generated once, kept on rerun)
- `app_for(slug, name, provider, url)` creates the Application and binds it to `homelab-admins`
- `env(path, KEY=value)` hands a value to `apply-sso-env.py` for the tool's `.env`
- for forward auth use `proxy(name, host)` instead of `oidc()`

### Gotchas

- Do not add `Authorization` to the shared `authentik@file` middleware's
  response headers: Traefik strips headers listed there from requests.
- OIDC redirect URIs are strict, so each tool only works on its one hostname.
- Containers resolve `sso.holy-grail.ch` via `extra_hosts` to `192.168.1.2`.
- New proxy providers need `set_oauth_defaults()` (handled by `proxy()`).
- The embedded outpost takes about 30 s to pick up a new app (404 meanwhile).
- Home Assistant 2026.10 ignores YAML `http:`: proxy trust lives in
  `.storage/http` (`trusted_proxies` `172.24.0.0/16`, as Traefik's IP is unpinned).
- A Home Assistant browser on the IP URL needs `?skip_oidc_redirect=true`.
- AdGuard locks out after 5 bad auths for 15 minutes.

### Pending (stage 2)

- [ ] Confirm one SSO login per tool
- [x] wg-easy: set `DISABLE_PASSWORD_AUTH=true` and recreate, remove `WG_EASY_ADMIN_PASSWORD` from `.env` / `.env.example`, verify `/api/auth/password` is rejected (2026-10-19, 403)
- [ ] AdGuard: confirm the UI opens without its own login prompt after SSO

## Branding

The login page, flow titles, favicon and emails all say **Holy Grail**, not
authentik. Three separate mechanisms, because authentik has no single switch:

**1. Brand object** (System -> Brands, or the ORM). Controls the login page:

| Field | Value |
|---|---|
| `branding_title` | `Holy Grail` |
| `branding_logo` | `holy-grail-logo.png` (the grail icon, 1024px) |
| `branding_favicon` | `holy-grail-icon.svg` (scales crisply in the tab) |
| `footer_links` (on the **Tenant**, not the Brand) | holy-grail.ch + a small authentik credit |

**2. Flow titles.** The big "Welcome to authentik!" line is the *flow's* `title`,
not a brand setting. Four flows carried it: `default-authentication-flow`,
`default-source-authentication`, `default-source-enrollment` and `initial-setup`.

**3. Emails** — see `custom-templates/email/base.html`.

### Where the logo files live, and why

The icon set lives in **`/home/pi/Projects/HolyGrail-Branding/`**, not in this
project - it is shared with other services and has its own README. Nothing here
holds a copy; `data/media/public/` contains **symlinks** into that store, so
updating the artwork there updates authentik with no copying.

`branding_logo` is **not** a free-form URL. `FileManager.file_url()` passes a value
through untouched only if it starts with `http:`, `https://` or `fa://`; anything
else is resolved as a managed file at `{base_dir}/media/{schema}`, i.e.
`/data/media/public`. A `data:` URI does **not** work - it gets prefixed into
`/files/media/public/data:image/svg+xml;...` and 404s. Files are served over a
**signed** URL (`?token=...`), so fetching `/files/media/public/<name>` without the
token returns 404 - correct, not a fault.

Two mounts in `docker-compose.yaml` make this work, on **both** server and worker:

```yaml
- /home/pi/Projects/HolyGrail-Branding/icons/android-chrome-192x192.png:/web/icons/icon_left_brand.png:ro
- /home/pi/Projects/HolyGrail-Branding/icons:/home/pi/Projects/HolyGrail-Branding/icons:ro
```

The second mounts the store at the **same absolute path** it has on the host. That
is required, not cosmetic: a symlink inside a bind mount resolves in the
*container's* namespace, so a link to `/home/pi/Projects/...` would dangle inside
the container unless that exact path also exists there.

To change the artwork, edit the store and run its deploy script - see
`/home/pi/Projects/HolyGrail-Branding/README.md`. It handles the two things that
are not automatic: Cloudflare caches the logo for four hours (hence md5-prefixed
filenames), and `logo_data()` is `lru_cache`d (hence a restart).

## Dashboard look

The user dashboard ("My applications", `/if/user/#/library`) is config as code. It has
sections, self-hosted icons, descriptions, a navy and gold theme, apps opening in a new
tab, and the wake helpers hidden. Re-apply after adding an app or changing the look:

```bash
cd Docker/Authentik
./scripts/fetch-app-icons.sh                                     # icons -> data/media/public/apps/
docker compose exec -T server ak shell < scripts/dashboard-look.py
```

Both scripts are idempotent.

- **`fetch-app-icons.sh`** downloads SVGs from homarr-labs/dashboard-icons (Apache-2.0)
  at a **pinned commit**. Files are named `apps/<slug>-<md5-8>.svg`; the hash beats
  Cloudflare's 4-hour media cache. The logos are their owners' trademarks and this repo
  is public, so only the script and its icon list are committed. The SVGs live in the
  gitignored `data/`. The script opens the read-only `data/media/public` only to
  create `apps/` once.
- **`dashboard-look.py`** sets only look fields: `group`, `meta_description`,
  `meta_publisher`, `meta_icon`, `open_in_new_tab` and `meta_hide`, plus the brand's
  `branding_custom_css`. Launch URLs, providers, bindings, flows and footer links are
  untouched. It warns about missing slugs and lists apps it doesn't manage. To add an
  app, add a line to `APPS` (and to `ICONS` in the fetch script).
- **Hidden helpers:** `jellyfin-wake` and `nextcloud-wake` have `meta_hide=True`. That
  only removes the tile; their providers and bindings still work.
- **Sections** sort A to Z in authentik, so a custom CSS rule moves Media first. That
  works in grid view only, because list view is a plain block.
- **The custom CSS relies on undocumented internal selectors** (`[part=app-list]`,
  `[part=card]`, `[data-group-id]`, `[part=background-wrapper]`,
  `:host([theme=dark])`), read from the 2026.8.4 source. **Re-check the dashboard after
  every authentik upgrade.** authentik adopts brand CSS into every component, so each
  rule is scoped to dashboard parts. The login and recovery flows were checked
  unchanged, and recovery-link (safe-mode) sessions get no custom CSS at all.
- **Why the navy background is CSS, not `settings.theme.background`:** that attribute
  is an inline style applied in light mode too, where the dark title text would sit on
  navy. The CSS rule is scoped to dark theme; light-mode users keep the stock look plus
  the gold hover ring.
- **Grid or list** is a per-browser toggle (phones always get list view). Admins can't
  set a default. In grid view the description sits behind each tile's ⋮ menu; in list
  view it shows inline.

## Routing

`sso.holy-grail.ch` is routed by Traefik's file provider
(`Docker/Traefik/traefik/dynamic/sso.yml`) to `http://authentik-server:9000`,
on `websecure` with a Cloudflare-resolver TLS certificate.
