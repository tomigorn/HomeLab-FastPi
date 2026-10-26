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
   enrollment user-write stage. Everything else is by hand (Directory → Groups → group → Users → Add existing user):
   `streaming-requesters` (Requests), `streaming-admins` (download apps, Jellyfin admin),
   `cloud-users` / `cloud-admins` (Nextcloud). See "Media groups" below.

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
- `authentik-server` — web UI + API (ingress over `traefik_authentik`, shared only with Traefik; other apps cannot reach :9000)
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
     an **SMTP key**; these become `AUTHENTIK_EMAIL__USERNAME` (`.env`) and
     `secrets/email_password`.
   - Any equivalent provider (Resend, MailerSend, Scaleway TEM…) works — just
     change `AUTHENTIK_EMAIL__*`.

4. **Config and secrets** — `.env` holds only non-secret config; secrets are files in `secrets/` (compose `secrets:`, read as `POSTGRES_PASSWORD_FILE` and Authentik `file:///run/secrets/…` values):
   ```bash
   cp .env.example .env    # fill in AUTHENTIK_EMAIL__USERNAME
   umask 077; mkdir -p secrets
   openssl rand -base64 36 | tr -d '\n' > secrets/pg_pass
   openssl rand -base64 60 | tr -d '\n' > secrets/secret_key
   printf %s '<Brevo SMTP key>' > secrets/email_password
   sudo chown 70:65019 secrets/pg_pass && sudo chmod 0440 secrets/pg_pass
   sudo chown 65019:65019 secrets/secret_key secrets/email_password && sudo chmod 0400 secrets/secret_key secrets/email_password
   ```
   An unreadable file silently becomes an empty value in Authentik: check `docker logs authentik-server | grep "Failed to read config"` after a change.

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

## Login lifetime

| Layer | Value | Set by |
|---|---|---|
| Login (stage `default-authentication-login`) | 1 day; 30 days when "stay signed in" is ticked (`session_duration days=1`, `remember_me_offset days=29`) | `scripts/session-ttl.sh apply` (since 2026-10-23; before: until the browser closed) |
| Forward-auth apps (all proxy providers) | 24 h, renewed silently while the login lives | same script |
| OIDC apps | access 5 min–1 h, refresh 30 days (provider defaults) | provisioning scripts |

`scripts/app-cache-on-group-change.sh` (timer `systemd/authentik-app-cache.timer`, every minute, installed in `/etc/systemd/system/`) — Authentik caches each user's dashboard app list for 24 h and clears it only on a save, not when group members change (adding a user to a group left their new apps hidden). The script fingerprints memberships + group hierarchy and deletes only the cached app lists when that changes; `--force` clears now. Access itself was never affected (policy results cache 5 min). Install: `sudo install -m 644 systemd/authentik-app-cache.* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now authentik-app-cache.timer`.

`scripts/canary-verify.sh [<app-url> <text>]` — real login + MFA as the canary (a normal user, no groups); with the two arguments it also opens that forward-auth app and expects the text, e.g. `canary-verify.sh https://specs.holy-grail.ch/ "Holy Grail · Machines"`. An admin-only app ends at the authorize page (APP_FAIL), which is the expected result for the canary.

`scripts/session-ttl.sh status|apply|rollback` — `apply` saves the old values to `backups/session-ttl-before.json`, then verifies a real login + MFA with the canary (which now answers "stay signed in") and rolls back on failure.

## Admin SSO (homelab-admins)

Nine admin tools sit behind Authentik: Traefik dashboard, Grafana, Portainer,
AdGuard Home, wg-easy, Home Assistant, Claude mockups and the two qBittorrent/VPN status pages. Access to each is an Authentik
Application group binding to `homelab-admins` (an application with a binding is
denied to everyone the bindings don't pass). All nine hostnames are reachable from
LAN and VPN only, via the `local-networks@file` Traefik middleware. The whole
setup is config as code in `scripts/provision-admin-sso.py`; the design is in
`docs/superpowers/specs/2026-10-18-homelab-admin-sso-design.md`.

**SSO only (2026-10-19).** No web UI accepts a username/password login over the
network (internet, LAN or VPN); the old break-glass logins are gone (plan
`docs/superpowers/plans/2026-10-19-sso-only-batch-a.md`, evidence in
`docs/superpowers/specs/2026-10-19-sso-only-inventory.md`). When Authentik is down,
recovery happens from a **server shell only**: flip an env flag and recreate, run a
CLI reset, or open an ssh tunnel to a port bound to 127.0.0.1. Remote shell without
the VPN: the Cloudflare SSH tunnel (see `WireguardVPN/README.md`). Machine access
(API keys, service-account tokens, agents, scrapers) is unaffected.

| Tool | URL | Method | Shell recovery |
|---|---|---|---|
| Traefik dashboard | https://traefik.holy-grail.ch | forward auth (`authentik@file`) | none over the network (basicAuth router removed 2026-10-19). Shell: `docker logs traefik`, the access log, or drop a temporary router file into `Traefik/traefik/dynamic/` (watched, no restart) |
| Grafana | https://grafana.holy-grail.ch | native generic OAuth (role `GrafanaAdmin` from groups) | login form + Basic auth disabled, port `127.0.0.1:3001`. Shell: set `GF_AUTH_DISABLE_LOGIN_FORM=false` in `grafana/docker-compose.yaml`, `docker compose up -d`, `ssh -L 3001:127.0.0.1:3001 fastpi`, log in at `http://localhost:3001/login?disableAutoLogin=true`, set it back; lost password: `docker exec grafana grafana cli admin reset-admin-password <pw>` |
| Portainer | https://portainer.holy-grail.ch | native OAuth (CE "Custom"; user `tomigorn` pre-created as admin, auto-provisioning off) | `POST /api/auth` refused by Traefik (router `portainer-password-login-block`), port `127.0.0.1:9443`. Shell: `ssh -L 9443:127.0.0.1:9443 fastpi`, then `https://localhost:9443/#!/internal-auth` as the initial admin; lost password: stop the container, `docker run --rm -v docker_portainer_data:/data portainer/helper-reset-password` |
| AdGuard Home | https://adguard.holy-grail.ch | forward auth; Authentik injects HTTP Basic for AdGuard user `authentik-proxy` (middleware `authentik-basic@file`; credentials in `homelab-admins` group attributes `adguard_username` / `adguard_password`) | no human user (only `authentik-proxy`). Shell: add a user (bcrypt hash) under `users:` in `adguard/conf/AdGuardHome.yaml` with the container stopped, start it, `ssh -L 3000:127.0.0.1:3000 fastpi`; steps in `adguard/docker-compose.yaml` |
| wg-easy | https://wg-easy.holy-grail.ch | native OIDC (custom `email_verified` scope mapping; admin linked by email) | password login disabled (`DISABLE_PASSWORD_AUTH=true`). Shell: set it to `false` in `WireguardVPN/docker-compose.yaml`, `docker compose up -d`, log in at `/login?auto_launch=false`, set it back; lost password: `docker exec -it WireGuard-VPN cli db:admin:reset` |
| Home Assistant | https://ha.holy-grail.ch | `hass-oidc-auth` 1.2.1 (public client) | none over the web: re-add the `homeassistant` auth provider from the shell + restart (see Home-Assistant README) |
| Claude mockups | https://claude-mockups.holy-grail.ch | forward auth (`authentik@file`); the answer-inbox POST is same-origin and rides the session cookie | none over the web (basic auth removed 2026-10-19). Shell: read `Claude-Mockups/www/` and `answers/` directly; steps in `Claude-Mockups/README.md` |
| VPN status (beefy) | https://vpn-status-beefy.holy-grail.ch | forward auth (`authentik@file`), then beefy's wake gate; the page has no login of its own | `ssh -L 8187:127.0.0.1:8087 beefy`, then `http://localhost:8187/` (8087 on beefy's LAN IP is dropped for all but fastpi) |
| VPN status (mouse) | https://vpn-status-mouse.holy-grail.ch | forward auth; Authentik injects port_updater's own HTTP Basic login (middleware `authentik-basic@file`; `homelab-admins` attributes `port_updater_username` / `port_updater_password`) | `ssh -L 8087:127.0.0.1:8087 fastpi`, then `http://localhost:8087/` with the Basic login (`WEB_USER` + `mouse/secrets/port_updater_web_pass`) |

**Dependency-Track (beefy)** is the one admin tool on the internet (Cloudflare tunnel), in its own script `scripts/provision-dt-sso.py`:

| App (slug) | Provider | Group | Notes |
|---|---|---|---|
| Dependency-Track (`dt`) | forward auth `dt-proxy` | `homelab-admins` | https://dt.holy-grail.ch, outer gate (Traefik `dynamic/dt.yml`), then beefy's wake gate |
| Dependency-Track login (`dt-login`, hidden) | OIDC `dt-login`, public (PKCE), scopes openid/email/profile | `homelab-admins` | DT's "Sign in with Holy Grail". Issuer `https://sso.holy-grail.ch/application/o/dt-login/`, redirect `/static/oidc-callback.html`; client id → beefy `Dependency-Track/.env`. Break-glass: DT's local `admin` (only reachable after the forward auth) |

```bash
cd Docker/Authentik && scp -q scripts/apply-sso-env.py beefy:/tmp/ \
  && docker compose exec -T server ak shell < scripts/provision-dt-sso.py 2>/dev/null \
  | ssh beefy python3 /tmp/apply-sso-env.py --base /home/buntu/Projects/Docker
```

### Re-running the provisioning

```bash
cd Docker/Authentik
docker compose exec -T server ak shell < scripts/provision-admin-sso.py | python3 scripts/apply-sso-env.py
```

The script is idempotent. Secrets never touch the terminal or git: the script emits `ENV <dir>/.env KEY=value` lines (client ids) and `FILE <dir>/secrets/<name> <uid>:<gid> <mode> value` lines (client secrets); `apply-sso-env.py` writes them into the gitignored `.env` / secret files, printing names only.

| Line | Written to | How |
|---|---|---|
| `ENV` | `<dir>/.env`, key replaced in place | as the caller, mode kept |
| `FILE` | `<dir>/secrets/<name>`, bare value, no newline | own uid: directly; other owner: `sudo -n install -o -g -m /dev/stdin <path>` (value on stdin). Refused unless `git check-ignore` says ignored; modes 0400/0440/0600/0640 only |

| Secret | File | Owner, mode |
|---|---|---|
| Grafana | `grafana/secrets/grafana_oauth_client_secret` | 65050:65050 0400 |
| wg-easy | `WireguardVPN/secrets/oidc_client_secret` | 0:0 0400 |
| Ryot (beefy) | `Ryot/secrets/ryot_oidc_client_secret` | 1001:1001 0400 |
| Portainer, Seerr (beefy) | still `.env` (`PORTAINER_OAUTH_CLIENT_SECRET`, `SEERR_OIDC_CLIENT_SECRET`): no container reads it, only their configure step | |

Restart the app afterwards (it reads the file at start). Preview without writing: `... | python3 scripts/apply-sso-env.py --dry-run` prints `would set` / `would write <path> (<owner> <mode>)`. The AdGuard proxy password is
only set when you pass it in (`docker compose exec -T -e ADGUARD_PROXY_PASSWORD server ak shell ...`),
i.e. when rotating it; otherwise the stored attributes are left untouched. Same for
port_updater's Basic login: `-e PORT_UPDATER_PROXY_USER -e PORT_UPDATER_PROXY_PASSWORD`
(values from `mouse/.env` `WEB_USER` and `mouse/secrets/port_updater_web_pass`), needed again
whenever that password changes.

To add a new app, add a block to `provision-admin-sso.py` using the helpers:

- `oidc(name, redirects, ...)` creates the OIDC provider (client id/secret generated once, kept on rerun)
- `app_for(slug, name, provider, url)` creates the Application and binds it to `homelab-admins`
- `env(path, KEY=value)` hands a non-secret value to `apply-sso-env.py` for the tool's `.env`
- `secret_file(path, "<uid>:<gid>", "0400", value)` hands a secret to it for the tool's secret file
- for forward auth use `proxy(name, host)` instead of `oidc()`

### Media groups

Three independent groups (no parent nesting), owner `tomigorn` in all three. Config as code: `scripts/provision-media-groups.py` (idempotent; `docker compose exec -T server ak shell < scripts/provision-media-groups.py`; tests `python3 -m unittest discover -s scripts`).

| Group | Apps | Who |
|---|---|---|
| `streaming-users` | Jellyfin (+ wake page), Tracker (+ login) | every invitee, automatic |
| `streaming-requesters` | Requests (+ login) | by hand |
| `streaming-admins` | Radarr, Sonarr, Prowlarr, Bazarr, SABnzbd, qBittorrent; Jellyfin administrator (OIDC plugin `AdministratorGroup`, re-checked at every sign-in) | by hand |

- A requester or admin who should also watch needs `streaming-users` too (groups do not imply each other).
- Cup (image versions of every host) is `homelab-admins`, not a media tool.
- Check who may open what: `ak shell` with `PolicyEngine(app, user)`, `build()`, then `passing` per app (done 2026-10-20 for each group alone: only its own apps pass).

Apps on beefy that are not admin-only live in `scripts/provision-media-sso.py` (same
helpers, but the group is per app); the older arr apps were created by hand (see
`Traefik/docs/2026-10-06-authentik-sso.md`).

| App (slug) | Provider | Group | Notes |
|---|---|---|---|
| Sonarr (`sonarr`) | forward auth `sonarr-proxy` | `streaming-admins` | like Radarr |
| Requests (`requests`) | forward auth `requests-proxy` | `streaming-requesters` | outer gate for Seerr, stays on |
| Requests login (`requests-login`, hidden) | OIDC `requests-login`, confidential, scopes openid/email/profile | `streaming-requesters` | Seerr's "Sign in with Holy Grail" (preview image). Issuer `https://sso.holy-grail.ch/application/o/requests-login/`, redirects `/login` + `/profile/settings/linked-accounts`. Client id/secret go to beefy `Seerr/.env` |
| Tracker (`tracker`) | forward auth `tracker-proxy` | `streaming-users` | outer gate for Ryot (beefy), stays on. In `scripts/provision-tracker-sso.py` |
| Tracker login (`tracker-login`, hidden) | OIDC `tracker-login`, confidential, scopes openid/email/profile | `streaming-users` | Ryot's "Sign in with Holy Grail". Issuer `https://sso.holy-grail.ch/application/o/tracker-login/`, redirect `/api/auth`. Client id goes to beefy `Ryot/.env`, the secret to `Ryot/secrets/ryot_oidc_client_secret` |
| Machines (`server-specs`) | forward auth `server-specs-proxy` | none: every logged-in user | specs.holy-grail.ch (Server-Specs). In `scripts/provision-specs-sso.py` (`REMOVE = True` takes it out again) |

Run it (the ENV lines carry the Seerr client id/secret to beefy, key names only on screen):

```bash
cd Docker/Authentik && scp -q scripts/apply-sso-env.py beefy:/tmp/ \
  && docker compose exec -T server ak shell < scripts/provision-media-sso.py 2>/dev/null \
  | ssh beefy python3 /tmp/apply-sso-env.py --base /home/buntu/Projects/Docker
```

Then on beefy `~/Projects/Docker/Seerr/scripts/configure.sh` puts them into Seerr.

Tracker (Ryot on beefy), written into beefy `Ryot/.env` + `Ryot/secrets/`, then on beefy `cd ~/Projects/Docker/Ryot && sudo docker compose up -d`:

```bash
cd Docker/Authentik && scp -q scripts/apply-sso-env.py beefy:/tmp/ \
  && docker compose exec -T server ak shell < scripts/provision-tracker-sso.py 2>/dev/null \
  | ssh beefy python3 /tmp/apply-sso-env.py --base /home/buntu/Projects/Docker
```

### Gotchas

- Do not add `Authorization` to the shared `authentik@file` middleware's
  response headers: Traefik strips headers listed there from requests.
- OIDC redirect URIs are strict, so each tool only works on its one hostname.
- Containers resolve `sso.holy-grail.ch` via `extra_hosts` to `192.168.1.2`.
- New proxy providers need `set_oauth_defaults()` (handled by `proxy()`).
- The embedded outpost takes about 30 s to pick up a new app (404 meanwhile).
- Home Assistant 2026.10 ignores YAML `http:`: proxy trust lives in
  `.storage/http` (`trusted_proxies` `172.24.0.0/16`, as Traefik's IP is unpinned).
- Home Assistant has no password login at all; Holy Grail works only on https://ha.holy-grail.ch (strict redirect URI).
- AdGuard locks out after 5 bad auths for 15 minutes.

### Pending (stage 2)

- [ ] Confirm one SSO login per tool
- [x] wg-easy: set `DISABLE_PASSWORD_AUTH=true` and recreate, remove `WG_EASY_ADMIN_PASSWORD` from `.env` / `.env.example`, verify `/api/auth/password` is rejected (2026-10-19, 403)
- [ ] AdGuard: confirm the UI opens without its own login prompt after SSO
  (2026-10-19: the injected `authentik-proxy` credentials return 200 on `/control/status`;
  the `admin` user is removed)

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
  create `apps/` once. Our own icons (`icons/<slug>.svg`, Holy Grail style, e.g. the
  avatar picker) are committed and installed by the same script.
- **`dashboard-look.py`** sets only look fields: `group`, `meta_description`,
  `meta_publisher`, `meta_icon`, `open_in_new_tab` and `meta_hide`, plus the brand's
  `branding_custom_css`. Launch URLs, providers, bindings, flows and footer links are
  untouched. It warns about missing slugs and lists apps it doesn't manage. To add an
  app, add a line to `APPS` (and to `ICONS` in the fetch script, or an SVG in `icons/`).
- **Hidden helpers:** `jellyfin-wake` and `nextcloud-wake` have `meta_hide=True`. That
  only removes the tile; their providers and bindings still work.
- **Sections** sort A to Z in authentik; custom CSS `order` rules make it Media,
  Downloads · Beefy, Downloads · FastPi, Account, Homelab in both views (the list container is turned into a flex
  column for that).
- **Descriptions under the tile name** (grid view, >= 768 px): authentik 2026.8 shows
  `meta_description` only in the tile's `⋮` menu (and inline in list view, which is a
  per-browser toggle with no server default). The custom CSS renders that menu's closed
  state in-flow as a caption in the title's font: line 1 the description (a 2-3 word
  noun phrase), line 2 the wake note (`wakes Beefy · ~55 s`, `wakes Tower · ~110 s`),
  dimmer. The note is a `\n` in `meta_description`, shown as a line break with
  `white-space: pre-line` (also in the open menu). The template wraps the text in
  newlines, so pre-line renders a blank first line; the caption hides it with a one-line
  negative margin (`-1lh`, calc fallback) like the list view. That blank line takes
  `::first-line`, so the note is dimmed with a gradient clipped to the text
  (`background-clip: text`) instead, not smaller or italic. The caption area has a fixed
  height with `overflow: hidden` (the popover's UA default is `auto`), so tiles with and
  without a note align and never scroll. Opening `⋮` still shows the description
  and the admin's "Edit application" link. Verified on an offline copy of the 2026.8.4
  tile DOM (with the template's whitespace text nodes) and stylesheets; check on the
  live page too.
- **List view rows** (phones, < 768 px): authentik renders one string, description `·`
  publisher, so `meta_publisher` is cleared on every app. The CSS keeps the `\n` as a line break (description, then the wake note) and hides the blank first line the template whitespace
  would produce, with a one-line negative margin (`-1lh`, calc fallback). Lines after
  the first can't be styled separately there, so the note is not smaller in list view.
- **The custom CSS relies on undocumented internal selectors** (`[part=app-list]`,
  `[part=card]`, `[part=card-header-actions-menu]`, `[data-group-id]`,
  `[part=background-wrapper]`, `:host([theme=dark])`), read from the 2026.8.4 source. **Re-check the dashboard after
  every authentik upgrade.** authentik adopts brand CSS into every component, so each
  rule is scoped to dashboard parts. The login and recovery flows were checked
  unchanged, and recovery-link (safe-mode) sessions get no custom CSS at all.
- **Why the navy background is CSS, not `settings.theme.background`:** that attribute
  is an inline style applied in light mode too, where the dark title text would sit on
  navy. The CSS rule is scoped to dark theme; light-mode users keep the stock look plus
  the gold hover ring.
- **Grid or list** is a per-browser toggle (phones always get list view). Admins can't
  set a default. In grid view the description sits behind each tile's ⋮ menu (shown as
  a caption by the CSS); in list view it shows inline.

## Routing

`sso.holy-grail.ch` is routed by Traefik's file provider
(`Docker/Traefik/traefik/dynamic/sso.yml`) to `http://authentik-server:9000`,
on `websecure` with a Cloudflare-resolver TLS certificate.

### Client IP (audit log, reputation policy)

Authentik takes the **leftmost** `X-Forwarded-For` entry, and only from a trusted proxy.

| Setting | Value | Why |
|---|---|---|
| `AUTHENTIK_LISTEN__TRUSTED_PROXY_CIDRS` (`.env`) | `127.0.0.0/8,::1/128,10.24.15.3/32` | only Traefik (pinned on `traefik_authentik`) may set the header; other containers are logged as themselves |
| Traefik `real-ip@file` | XFF = one real client IP | an internet client can no longer prepend a fake IP (before 2026-10-24 it could: fake audit log, dodge or abuse the reputation lockout) |

Details: [Traefik README, Client IPs](../Traefik/README.md#client-ips). If Traefik's IP ever changes, update both, or every login shows Traefik's IP and the reputation policy lumps all users together.
