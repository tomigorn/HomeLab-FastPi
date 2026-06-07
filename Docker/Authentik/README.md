# Authentik — homelab SSO / identity provider

Central login (IdP) for the homelab. Provides OIDC/OAuth login into apps and,
later, an LDAP interface for legacy apps. Exposed at
**https://sso.holy-grail.ch** (Cloudflare Tunnel → Traefik → Authentik).

## Architecture

| Piece | Detail |
|---|---|
| Version | Authentik **2026.5.2** |
| Containers | `postgresql` (postgres:16-alpine) + `server` + `worker` — **no Redis** (removed upstream in 2025.10) |
| Network | DB on an internal network; `server` also joins `traefik_proxy` |
| Public route | `Traefik/traefik/dynamic/sso.yml` → `authentik-server:9000` |
| Config-as-code | `blueprints/mvp.yaml` (mounted at `/blueprints/custom/`) declares groups, providers, applications, bindings, and the ABS role-claim mapping; secrets injected from `.env` |

Specs/plans: `docs/superpowers/specs/` and `docs/superpowers/plans/`.

## What's wired today

- **Groups:** `admin`, `streaming`
- **OIDC apps (Mode 2):** Portainer (admin group only) and Audiobookshelf
  (admin + streaming). ABS maps the `admin` group claim → ABS Admin role
  automatically; Portainer CE can't map groups → role, so the first admin
  Portainer login is promoted manually once.

## Identity source — **Authentik is the source of truth** (decided 2026-06-07)

Users and groups live in **Authentik's own directory** (Postgres-backed, with
groups, RBAC, MFA). This is a deliberate, best-practice choice for this
homelab — not a fallback. We do **not** run Active Directory or a separate LDAP
directory, because:

- **AD** is for managing Windows fleets (domain join, GPOs) — heavyweight and
  irrelevant to SSO-ing a few web apps.
- A **separate LDAP directory** (OpenLDAP / FreeIPA / lldap) would be a second
  system to maintain for no current benefit. We have no existing directory to
  federate from, and no app that *requires* LDAP.

### When to revisit (the triggers)

| Trigger | Move |
|---|---|
| We adopt an app that can **only** authenticate via LDAP (e.g. **SMB shares**, some \*arr-adjacent tools) | Turn on **Authentik's LDAP *provider* (outpost)** — Authentik stays the source of truth and *also* speaks LDAP. **Do NOT** stand up a separate directory. |
| We acquire an existing directory (NAS LDAP, inherited AD) | Federate via an Authentik LDAP **source**. |
| We want accounts decoupled from Authentik (swap IdP without losing users) | Consider **lldap** as source of truth, Authentik federating from it. |
| None of the above | **Stay Authentik-local** (current state). |

> Note: deferred scope (SMB, \*arr) is the most likely future trigger — and the
> answer there is the **LDAP outpost**, keeping one source of truth, *not* AD.

## How apps integrate — two modes

Authentik protects apps two ways, chosen per app. Full decision guide + how-to:
**[`docs/auth-integration-modes.md`](docs/auth-integration-modes.md)**.

- **Mode 2 — OIDC/OAuth** (app's own login; real identity + roles): Portainer, ABS.
- **Mode 1 — forward-auth / Proxy Provider** (Traefik middleware gate; for apps
  with no native login): middleware is built in Traefik
  (`authentik-forwardauth.yml` + `_example-routes.yml`) but the Authentik-side
  Proxy Provider/outpost is **not built yet** — see that doc.

Rule of thumb: **OIDC if the app can, forward-auth if it can't.**

## Operational notes

- **Bootstrap:** initial admin `akadmin` + API token come from `.env`
  (`AUTHENTIK_BOOTSTRAP_*`). Change the admin password after first login.
- **Blueprint gotcha:** on very first boot the custom blueprint auto-apply can
  fail with a migration/startup race (`status=error`). Re-apply once:
  `docker compose exec worker ak apply_blueprint /blueprints/custom/mvp.yaml`
  → `successful`. Idempotent; fine on later restarts.
- **Secrets** live only in gitignored `.env` (template in `.env.example`).
