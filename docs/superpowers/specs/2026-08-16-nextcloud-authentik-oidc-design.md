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

**`cloud-users` only.** One group, matching the existing `streaming-users` naming.
Nextcloud admin rights stay local to Nextcloud, so no group provisioning and no
custom scope mapping are needed — `openid profile email` is enough. This drops the
"Nextcloud Profile" scope mapping from Authentik's guide as YAGNI.

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
- `overwriteprotocol` = `https`
- `overwritehost` = `cloud.holy-grail.ch`
- `trusted_proxies` += `192.168.1.2` (fastpi — Traefik NATs to the host address on the
  way to tower; confirm against the Nextcloud access log rather than assuming)

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
| Scope | `openid profile email` |
| User ID mapping | `sub` |
| Display name mapping | `name` |
| Email mapping | `email` |
| Group provisioning | off |

Sync clients (desktop, iOS, Android) work with OIDC via Nextcloud's Login Flow v2, which
opens a browser — no special handling needed.

## Risks and mitigations

**The Nextcloud login page becomes publicly reachable.** Mitigated by Traefik secure
headers, Nextcloud's own brute-force protection, and the existing `tower-wake-ratelimit`
which already stops a passing bot from using the tunnel as a power switch. Fronting
Nextcloud with an Authentik *proxy* provider would hide the login page but breaks WebDAV
and the sync clients, so it is rejected.

**Lockout.** Keep the local Nextcloud admin account and local password login enabled
throughout. Do not disable password login until OIDC is verified end to end, and even
then keep the local admin as the break-glass path.

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

## Out of scope

- Group provisioning / Nextcloud admin rights from Authentik.
- Any LDAP provider or outpost.
- Migrating existing local Nextcloud accounts onto Authentik identities.
