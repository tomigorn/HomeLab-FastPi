# Nextcloud on tower ← Authentik SSO (OIDC)

Date: 2026-08-16
Status: approved, ready to plan

## Goal

Users defined in Authentik (fastpi) log into Nextcloud (tower) with SSO. Membership
of a new `cloud-users` group decides who may use Nextcloud at all — a user outside the
group is refused by Authentik before Nextcloud is ever reached.

## Decisions

**OIDC, not LDAP.** The original request named LDAP, but the requirement is
"login with an Authentik user, gated by group", which OIDC serves better:

- Authentik's own docs call OIDC "usually the simplest SSO method for a new Nextcloud
  deployment", and reserve LDAP for one case we do not have — server-side encryption
  with per-user keys, which needs the cleartext password OIDC never exposes.
- LDAP has no native MFA. This IdP is deliberately mandatory-MFA, so LDAP would force
  either `password;123456` at the Nextcloud login box, or a bind flow that skips MFA
  entirely — making Nextcloud the one service that bypasses the MFA policy while
  holding all the files. OIDC applies the existing flows unchanged.
- LDAP needs an outpost container deployed on tower. OIDC needs no extra container.

**`cloud-users` + `cloud-admins`**, matching the existing `streaming-users` naming.
`cloud-users` grants access at all; `cloud-admins` additionally grants Nextcloud
administrator rights. Both are bound to the application with `policy_engine_mode: any`,
so a `cloud-admins` member who is not also in `cloud-users` still gets in.

Admin rights require a custom `Nextcloud Profile` scope mapping (scope `nextcloud`)
because Nextcloud's administrator group is hard-coded upstream as literally `admin` and
cannot be renamed — the mapping appends that string to the groups claim for
`cloud-admins` members. It emits only Nextcloud-relevant groups, not every Authentik
group, so Nextcloud does not provision noise like `streaming-users`.

Neither group sets `is_superuser`: that flag governs Authentik itself, and setting it
would hand out Authentik admin by accident.

**Published at `cloud.holy-grail.ch`**, Cloudflare Tunnel → Traefik → tower:8080,
matching every other service in this homelab.

## Architecture

Interactive login, two independent network paths:

```
Browser ──► Cloudflare Tunnel ──► Traefik (fastpi) ──► tower:8080 (Nextcloud)
   │                                    ▲
   │                              tower-wake-public
   │                          (rate limit → WoL gate)
   │
   └──► https://sso.holy-grail.ch  (Authentik authorize + consent)
              │
              └── policy binding: user ∈ cloud-users ?  no → denied here

Nextcloud (tower) ──► https://sso.holy-grail.ch  (server-to-server token exchange)
```

The server-to-server leg hairpins: tower resolves `sso.holy-grail.ch` publicly, exits
to Cloudflare, and comes back through the tunnel to Traefik on fastpi. No split-horizon
DNS needed.

The access gate lives in **Authentik**, not Nextcloud. Binding the application to
`cloud-users` means a non-member never receives a token, so no unwanted Nextcloud
account is ever provisioned.

## Components

### 1. Authentik — group

`cloud-users`, not a superuser group.

### 2. Authentik — OAuth2/OpenID Connect provider

| Setting | Value |
|---|---|
| Name | `Nextcloud` |
| Client type | Confidential |
| Authorization flow | existing `default-provider-authorization-explicit-consent` |
| Redirect URI (Authorization, Strict) | `https://cloud.holy-grail.ch/apps/user_oidc/code` |
| Redirect URI (Post Logout, Strict) | `https://cloud.holy-grail.ch` |
| Signing key | any available |
| Subject mode | Based on the User's UUID |

Record the generated Client ID and Client Secret.

### 3. Authentik — application + access gate

Application `Nextcloud`, slug `nextcloud`, bound to the provider above.
Then bind a **Group membership policy for `cloud-users`** to the application.
This binding is the whole access-control mechanism.

Discovery endpoint that results:
`https://sso.holy-grail.ch/application/o/nextcloud/.well-known/openid-configuration`

### 4. Traefik — new route

New file `Traefik/traefik/dynamic/nextcloud.yml`, following the `audiobookshelf.yml`
shape but pointing at an off-box IP instead of a container name:

- Router `nextcloud`, rule ``Host(`cloud.holy-grail.ch`)``, entryPoint `websecure`,
  `certResolver: cloudflare`.
- Middlewares: `tower-wake-public` (already exists — rate limit then WoL gate) plus a
  `nextcloud-secure-headers` block.
- Service → `http://192.168.1.101:8080`, `passHostHeader: true`.

Nextcloud sends its own CSP and is strict about it, so the headers middleware sets HSTS,
nosniff and referrer policy but does **not** inject a `Content-Security-Policy` — unlike
the audiobookshelf route, whose CSP would break the Nextcloud web UI.

### 5. Cloudflare — public hostname

The tunnel is token-based and therefore dashboard-managed. Add public hostname
`cloud.holy-grail.ch` → the Traefik origin, the same way the existing hosts are wired.
Nothing in this repo changes.

### 6. Nextcloud — reverse proxy configuration

Required before OIDC will work at all; without it Nextcloud generates `http://` URLs and
the strict redirect URI match fails:

- `trusted_domains` += `cloud.holy-grail.ch`
- `overwrite.cli.url` = `https://cloud.holy-grail.ch`
- `trusted_proxies` = `172.24.0.1`, `192.168.1.2`

**Corrected as-built (2026-08-16).** Two changes from the original plan, both verified
against the running system:

1. The proxy address is **`172.24.0.1`**, not `192.168.1.2`. Nextcloud's access log shows
   requests arriving through Cloudflare/Traefik from `172.24.0.1` — the gateway of
   fastpi's `traefik_proxy` bridge (`172.24.0.0/16`, Traefik itself at `172.24.0.9`),
   which reaches tower un-masqueraded. `192.168.1.2` appears only for requests made
   directly from the fastpi host. Both are listed. The original `192.168.1.2`-only guess
   would have silently broken OIDC.
2. **`overwritehost` and `overwriteprotocol` are deliberately NOT set.** With
   `trusted_proxies` correct, Nextcloud honours Traefik's `X-Forwarded-Proto`/`Host` and
   builds correct URLs on its own — verified: `https://cloud.holy-grail.ch/` returns a
   302 to `https://cloud.holy-grail.ch/login`. Forcing the host would canonicalise every
   request to the public name and degrade LAN access at `192.168.1.101:8080`, which is
   still a listed trusted domain.

Also set the upload chunk size below Cloudflare's free-tier 100MB per-request cap.
Nextcloud chunks uploads already; the default chunk can exceed the cap, so pin it
(e.g. 20MB) or large uploads fail with a 413.

### 7. Nextcloud — user_oidc

Install the **OpenID Connect user backend** (`user_oidc`) app, then configure:

| Setting | Value |
|---|---|
| Identifier | `authentik` |
| Client ID / secret | from step 2 |
| Discovery endpoint | `https://sso.holy-grail.ch/application/o/nextcloud/.well-known/openid-configuration` |
| Scope | `openid profile email nextcloud` |
| User ID mapping | `sub` |
| Display name mapping | `name` |
| Email mapping | `email` |
| Groups mapping | `groups` |
| Group provisioning | on |

Sync clients (desktop, iOS, Android) work with OIDC via Nextcloud's Login Flow v2, which
opens a browser — no special handling needed.

## Risks and mitigations

**The Nextcloud login page becomes publicly reachable.** Mitigated by Traefik secure
headers, Nextcloud's own brute-force protection, and the existing `tower-wake-ratelimit`
which already stops a passing bot from using the tunnel as a power switch. Fronting
Nextcloud with an Authentik *proxy* provider would hide the login page but breaks WebDAV
and the sync clients, so it is rejected.

**Lockout.** Keep the local Nextcloud admin account (`admin`) as the break-glass path.

**OIDC-only login (added 2026-08-16, at user request).**
`occ config:app:set user_oidc allow_multiple_user_backends --value=0` makes `/login`
302 straight to Authentik; the password form is no longer offered. The local form
remains reachable at **`/login?direct=1`**, which is the break-glass route and
**cannot be turned off by this setting**.

That leaves one real gap: `admin` is a database-backend account with a local password
and no MFA, reachable from the internet via `?direct=1` — the single path around an
otherwise mandatory-MFA IdP. Mitigate by giving `admin` a long random password and
enabling Nextcloud's own TOTP on it, rather than by trying to block `?direct=1` (doing
so would also destroy the only recovery path if OIDC breaks).

**tower is asleep at login time.** The WoL gate returns its self-refreshing "waking up"
page. Worst case the OIDC redirect lands during boot and the user retries; the
`?port=8080` probe already ensures tower is only reported ready once Nextcloud answers.

## Verification

1. `curl https://cloud.holy-grail.ch/status.php` returns the Nextcloud version JSON.
2. `testuser` (**not** in `cloud-users`) attempts login → refused by Authentik, and no
   account appears in Nextcloud.
3. Add `testuser` to `cloud-users` → login succeeds, account is provisioned, TOTP is
   demanded by the existing Authentik flow.
4. Remove from `cloud-users` → next login refused.
5. Upload a file larger than 100MB → succeeds via chunking.

**Group provisioning can fight manual group edits.** With provisioning on, `user_oidc`
owns group membership for the groups it manages: a user manually added to `admin` inside
Nextcloud can be removed again at next login. Manage Nextcloud group membership from
Authentik once this is live, not from Nextcloud.

## Out of scope

- Any LDAP provider or outpost.
- Migrating existing local Nextcloud accounts onto Authentik identities.
