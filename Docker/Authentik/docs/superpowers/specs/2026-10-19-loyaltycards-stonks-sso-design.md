# "Sign in with Holy Grail" for LoyaltyCards and Stonks: design

Date: 2026-10-19. Status: design only, nothing built or deployed. Authentik 2026.8.4 at
`https://sso.holy-grail.ch`. Companion plan:
`docs/superpowers/plans/2026-10-19-loyaltycards-stonks-sso.md`. Context and the other apps:
`docs/superpowers/specs/2026-10-19-sso-only-inventory.md` (rows "LoyaltyCards", "Stonks", section 3.9).

User requirement: disable local user login everywhere and allow only Authentik ("Holy Grail")
SSO. Recovery when Authentik is down is from the server shell only.

No secrets, emails or passwords are in this document. Evidence below was read from code, the
pocketbase v0.39.1 source notes in the inventory, the PocketBase docs
(pocketbase.io/docs/authentication) and read-only queries on a copy of the PocketBase DB.

## 1. Summary of the recommendation

| | LoyaltyCards (PocketBase `users`) | Stonks |
|---|---|---|
| Mechanism | PocketBase built-in OIDC provider `oidc` pointing at Authentik; `passwordAuth` off | Native OIDC in the FastAPI app (Authlib), signed session cookie as today |
| Why not the other option | Header auth does not exist in PocketBase | Forward auth + `X-authentik-username` is not safe enough here (section 4.2) |
| Authentik group | new `loyalty-users` | `homelab-admins` (single user, financial data) |
| Code change | PWA (Svelte) + a small Go config-reconcile in the PocketBase binary; custom TOTP removed in a later step | `app/oidc.py`, routes, config, template; password login stays behind `AUTH_MODE=password` for shell recovery |
| Admin side | `/_/` and `_superusers` endpoints denied at Traefik, `superuser ips`, shell recovery with the CLI | none |
| Recovery | env flag `OIDC_ONLY=false` + recreate (re-enables password) | env flag `AUTH_MODE=password` + recreate |

## 2. LoyaltyCards

### 2.1 Who the users are today (measured 2026-10-19, read-only copy of `data.db`, counts only)

- `users`: **2** records. 1 verified, 1 unverified. **0** have TOTP enabled (the custom TOTP
  feature is unused). Both still have a password set.
- External auth links: **1**, provider `google`. It belongs to the verified user.
- `cards`: **5**, all owned by that one verified user. The other user owns nothing.
- `_superusers`: **1**.
- Open signup is on today: `users.createRule` is the empty string (anyone may create).
- Matching to Authentik by email (compared by hash, nothing printed): the verified user with all
  5 cards **has a matching Authentik account** (the owner, member of all existing groups). The
  other (unverified, no data) user has **no** Authentik account.
- The `users` collection currently has a Google OAuth2 provider configured and enabled (the
  inventory said "configured, not enabled"; the PWA shows the button only if the backend lists
  it). Its client secret sits in plain text in the PocketBase DB (it was shown in tool output
  during this investigation, so treat that Google client secret as exposed: rotate or delete the
  OAuth client in the Google Cloud console as part of the cutover).

Consequence: this is effectively a single-user app. The account linking problem is small.

### 2.2 Linking existing accounts to Authentik identities

PocketBase `authWithOAuth2` resolves the record in this order (v0.39, `apis/record_auth_with_oauth2.go`
per the inventory): existing external-auth link, then the logged-in record, then **an existing
record with the same email**, which is auto-linked. The email is only used when the provider
reports `email_verified: true`. Authentik 2025.10+ reports `false` by default, so the Authentik
application needs the same custom scope mapping used for wg-easy
(`provision-admin-sso.py`: `ScopeMapping "wg-easy email (verified)"`, expression
`return {"email": request.user.email, "email_verified": True}`). It is acceptable here because
Authentik enrolment is invite-only with a verified email (same reasoning as wg-easy).

Result for the 2 existing users:

- The owner: first Holy Grail login links by email to the existing record, so all 5 cards stay.
  The old Google link stays in `_externalAuths` (harmless; delete the Google provider anyway).
- The unverified, data-less user: cannot log in any more (no Authentik account, passwords
  disabled). Question Q3 below: delete it or leave it.
- New users: created on first OIDC login only if the create rule passes. The rule becomes
  `@request.context = "oauth2"` (no REST signup, no password users). Access is gated by the
  Authentik application group binding anyway.

Fallback if the mapping was missing: linking silently never happens and creation fails because
`email` is required, so the plan takes a backup first and the user checks that the 5 cards are present after the
first login (Task 7), with a restore path if a duplicate empty user was created.

### 2.3 PocketBase settings (config as code, not clicks)

PocketBase configuration lives in its DB. To keep it reproducible this design adds an
idempotent reconcile function in the Go binary, run on every start from `OnServe` (the repo
already does the same for the token duration and rate limits in `main.go`):

- `users.oauth2.enabled = true`, one provider `oidc`:
  - `authURL` `https://sso.holy-grail.ch/application/o/authorize/`
  - `tokenURL` `https://sso.holy-grail.ch/application/o/token/`
  - `userInfoURL` `https://sso.holy-grail.ch/application/o/userinfo/`
  - `clientId` / `clientSecret` from env (generated by `provision-admin-sso.py`, written to the
    gitignored `.env` by `apply-sso-env.py`)
  - `pkce = true`, `displayName = "Holy Grail"`
  - `mappedFields.name = "name"`
- the Google provider is removed;
- `users.passwordAuth.enabled = false`;
- `users.createRule = @request.context = "oauth2"`.

Guard rails: gated by `OIDC_ONLY=true`. If it is true but client id or secret is empty the
function logs and changes nothing (no lockout by a typo). With `OIDC_ONLY=false` it restores
`passwordAuth.enabled = true` and `createRule = ""`, which is the rollback.

The PocketBase container must reach Authentik for the token and userinfo calls (server to
server). Containers resolve `sso.holy-grail.ch` via `extra_hosts` to `192.168.1.2` (Authentik
README gotcha), so `loyalty-sync` needs the same `extra_hosts` entry.

### 2.4 PWA changes

Existing code already has a redirect-based OAuth flow for Google
(`src/lib/auth/store.ts`: `loginGoogle()` stores PKCE verifier + state in localStorage, full-page
redirect; `completeGoogleLogin()` called from `App.svelte` on startup calls
`authWithOAuth2Code`). It exists because popups are unreliable in installed PWAs; PocketBase's
`authWithOAuth2()` popup flow also needs the click handler to be non-async on Safari. So the
design **reuses the redirect flow** and does not switch to `authWithOAuth2()`:

- Rename and generalise: `loginGoogle` -> `loginHolyGrail` (provider name `oidc`),
  `completeGoogleLogin` -> `completeOAuthLogin`, `googleEnabled` -> `oidcEnabled`.
- Redirect URL registered in Authentik: `https://loyalty-cards.holy-grail.ch/` (the PWA origin,
  what `oauthRedirectUrl()` already returns). PocketBase does not care which URL is used with
  `authWithOAuth2Code`. Optional second URI `https://loyalty-sync.holy-grail.ch/api/oauth2-redirect`
  only if the popup flow is ever wanted; not needed, so not registered (strict matching, fewer
  URIs).
- `AccountSection.svelte`: logged out shows one button "Sign in with Holy Grail" (plus the error
  line); logged in shows the account email and "Log out". Remove: email/password fields, signup,
  mandatory-2FA enrolment panel, `totpRequired`, `startTotp`, `confirmTotp`, `loginPassword`,
  `signup`, `googleLinked`, `disableTotp`. `Account.totpEnabled` is dropped.
- CSP (`Traefik/.../loyalty-cards.yml`): top-level navigation to `sso.holy-grail.ch` is not
  restricted by the current CSP (no `navigate-to`, no `form-action`); `connect-src` already has
  the sync host. No CSP change needed.

Offline and PWA caveats:

- Sign-in needs the network (redirect to Authentik). An already-signed-in PWA keeps working
  offline: the PocketBase token is persisted (about 3 years) and `refreshSession()` only clears
  on 401/403, not on network errors. No change.
- The callback lands on `/?code=...&state=...`. Workbox does not ignore those query parameters
  for precache matching, so the request is served by the navigation fallback (index.html). The
  plan verifies the `vite.config.ts` workbox `navigateFallback` setting; the Google flow worked
  the same way, so this is expected to be fine.
- The code verifier lives in localStorage so that, on Android, a return into the browser instead
  of the installed PWA still completes. On iOS standalone PWAs the redirect stays inside the
  same web view, so it works. First real login must be tested on the phone (user).
- Old tokens: existing sessions stay valid (3-year tokens). At cutover optionally invalidate
  them (section 2.7) so that nobody keeps a session minted through a password.

### 2.5 TOTP and MFA

Authentik already enforces MFA for the login. The custom TOTP (`totp.go`, `guards.go`,
`/api/loyalty/totp/*`, user fields `totpSecret|totpPending|totpEnabled`) becomes dead code once
`passwordAuth` is off: with the password endpoint 403, the guard never runs and nobody uses TOTP
(0 users have it on). Plan: step 1 only turns the password off (reversible, TOTP code stays
untouched so rollback keeps working); a later cleanup task removes the routes, guard, tests and
the rate-limit rules for them. The three DB fields are left in place (data hygiene, no destructive
migration); optional drop is listed as a question.

### 2.6 Superuser lockdown

Facts (inventory 3.9): `_superusers` cannot use OAuth2, only password (+OTP/MFA). So PocketBase
admin is the one login that cannot become SSO. Treat like Unraid root: shell-only, off the network.

Layers:

1. **Traefik**: a router on `Host(loyalty-sync...)` with `PathPrefix` `/_/`,
   `/api/collections/_superusers` and `/api/collections/pbc_3142635823` (the deterministic
   `_superusers` collection id), priority 100, middleware `ipAllowList` with a dummy range
   (`192.0.2.1/32`, the same pattern as `nextcloud-deny`), so everything gets 403, including
   LAN and VPN. This also blocks the unauthenticated brute-force target `/api/collections/_superusers/auth-with-password`.
2. **PocketBase `superuser ips`** as defence in depth: `docker exec loyalty-sync
   /pb/loyaltycards-sync superuser ips 127.0.0.1/32`. Enforced at superuser login and on every
   superuser-token request. Note it uses the client IP PocketBase sees; behind Traefik that is
   only the real address if the trusted-proxy header setting is correct, which is why it is
   layer 2, not layer 1. The plan checks what IP PocketBase sees.
3. **Shell recovery / admin**: CLI works on the DB directly and ignores IP rules:
   `docker exec loyalty-sync /pb/loyaltycards-sync superuser upsert <email> <password>`. For the
   dashboard: stop the Traefik rule (comment out, Traefik hot-reloads) or use a temporary `docker
   run` publishing `127.0.0.1:8090` on the same volume, then `ssh -L`. Procedure in the plan.
4. The `PB_ADMIN_EMAIL/PB_ADMIN_PASSWORD` env in compose is read on every start by
   `ensureSuperuser` (creates only when missing). It keeps a password in the container
   environment; after cutover set a long random value (kept in `.env`) and note it is unusable
   from outside.

This keeps the "SSO only" promise for every network-reachable login; the only password left is
the superuser one that nothing on any network can reach.

### 2.7 Authentik group

Recommended: **new group `loyalty-users`** with the owner as the only member. Reason: homelab-admins
is for admin tools and is the default in `app_for()`; LoyaltyCards is a user app, and per-app
groups are the existing pattern (`cloud-users`, `streaming-users`) so a family member can be
added later without admin rights.

Alternatives for Q1: (a) `homelab-admins` (zero new groups, but any future admin gets the app
and a future non-admin cannot be added without admin rights); (b) `cloud-users` (Nextcloud
group, semantically wrong); (c) `streaming-users` (media group, wrong meaning).

`app_for()` currently always binds `homelab-admins`; the plan adds an optional `group=` argument.

### 2.8 Migration and rollback

Order matters (see plan): 1) Authentik app + group; 2) backend change deployed with
`OIDC_ONLY=false` (nothing changes for users); 3) PWA released with the Holy Grail button
(password UI still hidden only after step 5); 4) user does the real first login on phone and
checks the 5 cards are still there; 5) set `OIDC_ONLY=true`; 6) Traefik superuser lockdown +
`superuser ips`; 7) optional: rotate the users auth-token secret to end old password-minted
sessions; 8) remove Google provider secret, delete the Google OAuth client; 9) cleanup of TOTP code.

Rollback by step: 5 -> set `OIDC_ONLY=false` and recreate (password login and signup rule back);
6 -> remove the router file / `superuser ips` with no argument; 3 -> redeploy the previous
PWA image tag (`IMAGE_TAG` in `LoyaltyCards/.env`); 2 -> previous image. Data: a backup of
`pb_data` (volume copy, `docker run --rm -v loyaltycards-sync_pb_data:/d -v $PWD:/b alpine tar`)
is the first step of the plan.

## 3. Open questions for the user (LoyaltyCards)

- Q1 Group: `loyalty-users` (recommended), or one of the alternatives in 2.7?
- Q2 Who else uses the app? Today 1 user with data. If nobody else, `loyalty-users` has one member.
- Q3 The second, unverified, data-less PocketBase user: delete it (recommended) or leave it dormant?
- Q4 Invalidate all old sessions at cutover (user logs in again once on every device)? Recommended yes.
- Q5 Admin dashboard exposure: fully denied at Traefik (recommended) or reachable from LAN/VPN
  with the superuser password (`local-networks@file`, simpler but a password login remains
  on the network)?
- Q6 Drop the unused `totp*` DB fields later, or keep them?

## 4. Stonks

### 4.1 Facts

- Code: `~/Documents/development/Stonks` (git, FastAPI, Jinja, Authlib not yet a dependency).
  Deploy dir `/home/pi/Projects/Docker/Stonks`; `redeploy.sh` rebuilds `stonks:latest` from the code repo.
- Login: `app/web/routes.py` `POST /login` (username + argon2 hash from env, IP rate limit),
  cookie `stonks_session` (itsdangerous signed `{"u": username}`, 30 days, httponly, secure,
  lax); `current_user` dependency in `app/web/deps.py` redirects to `/login`. Unauthenticated
  routes: `/login`, `/logout`, `/static`, `/healthz`.
- Telegram: python-telegram-bot long polling started in the app lifespan; authorisation is by
  `TELEGRAM_CHAT_ID`, completely separate from the web login. Not affected by any option.
- Network: no published ports (`docker port stonks` is empty); only network `traefik_proxy`,
  which is shared with about 16 other containers. Uvicorn runs with `--forwarded-allow-ips "*"`.

### 4.2 Native OIDC vs forward auth

Forward auth + trusting `X-authentik-username` is safe only if nothing but Traefik can reach
the app. Here: no host port (good), but `traefik_proxy` is a shared network, so any of the
other 17 containers can call `http://stonks:8000` with a forged `X-authentik-username` header
and be logged in. That makes every container on the network a path to the finance data. It
could be mitigated (a second private network for stonks, a Traefik-injected shared secret
header, verifying the signed `X-authentik-jwt`) but each is bespoke machinery. Native OIDC has
no such trust assumption: the app validates the code exchange itself. It also gives the
standard login behaviour and needs about 60 lines. **Recommendation: native OIDC.**

Alternative for Q7: forward auth (route pattern in `cup.yml`) plus a private network for
stonks and the header check. Less code in the app, more infrastructure. Not recommended.

### 4.3 Design

- New settings: `AUTH_MODE` (`oidc` or `password`, default `password` so the code can ship
  before the switch), `OIDC_ISSUER` (`https://sso.holy-grail.ch/application/o/stonks/`),
  `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `PUBLIC_URL` (`https://stonks.holy-grail.ch`).
- Routes (oidc mode): `GET /auth/login` starts the flow (Authlib, PKCE S256, state in a
  Starlette `SessionMiddleware` cookie), `GET /auth/callback` exchanges the code, reads
  `preferred_username` (fallback `email`) from userinfo, sets the existing `stonks_session`
  cookie via `make_session`. `GET /login` shows a page with one button "Sign in with Holy
  Grail"; `POST /login` returns 404 (the password form code remains but is unreachable).
  `current_user` redirects to `/auth/login` in oidc mode. `POST /logout` clears the cookie and
  lands on `/login` (button page, no auto re-login). The Authentik session stays; a full logout
  is an Authentik logout.
- Password mode is unchanged (existing tests stay green): this is the shell recovery switch.
- Access control: Authentik application bound to group `homelab-admins` (the owner). The app
  does not hold its own allow-list (YAGNI; the binding is the gate).
- Strict redirect URI in Authentik: `https://stonks.holy-grail.ch/auth/callback`.
- Container needs `extra_hosts: sso.holy-grail.ch:192.168.1.2` to fetch the discovery document
  and token endpoint.
- Traefik: no change for native OIDC (CSP `form-action 'self'`: the login button is a link
  (`<a href="/auth/login">`) and a redirect, so form-action does not apply; the flow redirects
  are top-level navigations).
- Env: `.env` and `.env.example` get the four new variables (secret blanked in the example),
  `APP_PASSWORD_HASH` stays in `.env` for recovery.
- Rollback: `AUTH_MODE=password` in `.env`, `docker compose up -d`.

## 5. Testing strategy

Unit/automated (TDD, details in the plan):

- Stonks: pytest with Authlib client methods monkeypatched (no network): login redirect, callback
  sets cookie, callback with missing userinfo fails, `POST /login` is 404 in oidc mode, password
  mode unchanged, `current_user` redirect target per mode, logout.
- PocketBase Go: `go test` (via `golang:1.25-alpine` in Docker; host has no Go): reconcile
  function turns password off, sets provider, createRule; guard rails (missing client secret ->
  unchanged); `auth-with-password` returns 403 via `tests.ApiScenario`; rollback restores. Existing
  owner-isolation tests stay green.
- PWA: vitest for the store functions (redirect URL, state mismatch, provider lookup) and
  `AccountSection` (button visible, no password fields); existing Playwright smoke/auth specs
  updated.
- Authentik provisioning: the script is idempotent; verify with an `ak shell` read-only query
  (providers, redirect URIs, mapping, binding).

End to end without the user (from the Pi only, internal Host header, never from the public
side, CrowdSec bans the home IP):

- `curl --resolve` to Traefik on `127.0.0.1:443` or container-to-container requests:
  `GET /api/collections/users/auth-methods` lists provider `oidc` and not `google`/password;
  `POST .../auth-with-password` -> 403; `/_/` and `_superusers` paths -> 403 through Traefik;
  Stonks `/healthz` 200, `/login` shows the Holy Grail button, `/auth/login` returns 302 to
  `sso.holy-grail.ch/application/o/authorize/` with the expected `client_id`, `redirect_uri`,
  `code_challenge`; `POST /login` 404.
- Headless browser is possible up to the Authentik login page only. **The user must do the first
  real login** (MFA) for both apps, and confirm the 5 LoyaltyCards cards are still present.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Authentik down = nobody can sign in | Existing sessions keep working (PWA 3 years, Stonks 30 days); shell flags `OIDC_ONLY=false`, `AUTH_MODE=password` |
| Linking fails (email_verified false) and creates a duplicate empty user | Custom verified mapping; test with a throwaway; backup before; user checks cards after first login; createRule blocks stray signups after |
| PocketBase can't reach Authentik from the container | `extra_hosts`; curl from inside the container is a plan step |
| Lockout by setting `OIDC_ONLY=true` with a bad client secret | Guard rail: empty id/secret -> no change; flip only after the real login succeeded |
| PWA redirect returns to browser, not the installed app (Android) | verifier in localStorage; user tests on phone |
| `superuser ips` blocks the real admin because PocketBase sees the Traefik IP | Layer 2 only; test what IP is seen; CLI works regardless |
| Google client secret is in the PocketBase DB and was displayed in tool output | Remove provider; rotate/delete the OAuth client in Google Cloud (user) |
| `provision-admin-sso.py` has uncommitted edits by someone else | The plan's commit steps stage only own hunks (`git add -p`) |
| Authlib new dependency | pinned, tests, rollback = old image tag (`docker tag` before rebuild) |
| `@request.context = "oauth2"` create rule semantics | verified by a Go test + a real call before relying on it |
| Stonks cookie lifetime 30 days outlives an Authentik deactivation | accepted; session key rotation (`SESSION_SECRET`) ends all sessions |

## 7. Documentation updates after build

Authentik README table (add two rows and recovery commands), inventory rows, `Docker/_global/checklist.md`
(new rows must stay unchecked, never add checkmarks), the LoyaltyCards-Sync README/DEPLOY.md
(open signup note obsolete), the LoyaltyCards project memory note.
