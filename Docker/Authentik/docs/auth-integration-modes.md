# Authentik integration modes — forward-auth middleware vs. native OIDC

Authentik can protect an app in **two fundamentally different ways**, and we
deliberately pick one per app. They run side-by-side off the same user/group
directory, so a single Authentik instance does both at once. This doc records
the decision so future-us doesn't re-litigate it.

---

## Mode 1 — Forward Auth / Proxy Provider (the Traefik middleware)

**What it is:** Authentik runs an *outpost*. Traefik calls it as a
`forwardAuth` middleware on a route. Every request is bounced off Authentik
first:

```
request → Traefik (someapp.holy-grail.ch)
        → middleware asks Authentik outpost "is this user logged in?"
        → not logged in  → 302 redirect to Authentik login
        → logged in      → request passes through to the app
```

**This is a gate in *front* of the app.** Its superpower: it works on apps
that have **no login of their own** — a raw dashboard, an internal tool, an
exporter, a static admin panel. You bolt SSO onto things that can't do auth
themselves, by adding one middleware to the Traefik router.

**The trade-off:** by default it only *gates access* — it does not necessarily
log you in *as a specific user inside the app*. The app still sees one
anonymous visitor. Authentik does inject trusted headers
(`X-authentik-username`, `X-authentik-groups`, `X-authentik-email`, …), so an
app that supports **header / proxy auth** can read who you are — but plain apps
won't, and role mapping is crude compared to OIDC.

**Use Mode 1 when:** the app has no/weak built-in login, or you just want an
access gate. Examples we might protect this way: dashboards, monitoring UIs,
internal tooling.

---

## Mode 2 — OIDC / OAuth2 Provider (native login inside the app)

**What it is:** the **app itself** has a "Login with OIDC/OAuth" button and
talks to Authentik directly. The app receives a real, verified identity plus
group claims, creates a proper per-user account, and maps roles.

**This is the better choice when the app supports it natively**, because you get
real identity + role mapping, not just a gate.

**Use Mode 2 when:** the app has native OIDC/OAuth (most modern self-hosted
apps do). Examples we use this way: **Portainer**, **Audiobookshelf**.

---

## Decision guide

| Question | → Mode |
|---|---|
| Does the app have native OIDC/OAuth login? | **Mode 2 (OIDC)** — best fidelity, real roles |
| App has no login, or weak/shared login? | **Mode 1 (forward-auth)** — gate it in Traefik |
| Need per-user roles *inside* the app? | **Mode 2** (Mode 1 can't map roles cleanly) |
| Just need "must be logged in to reach this"? | **Mode 1** — fastest to bolt on |

Rule of thumb: **OIDC if the app can, forward-auth if it can't.**

---

## Current state (MVP)

| App | Mode | Why |
|---|---|---|
| Portainer | **OIDC** | native OAuth; controls Docker socket, want real identity |
| Audiobookshelf | **OIDC** | native OIDC; maps `admin` group → ABS Admin role |

Both are OIDC because both support it and we want real role mapping. Mode 1
would have been a downgrade for them (no Portainer role distinction, messier ABS
accounts).

---

## How to actually use Mode 1 (forward-auth) — both halves required

The Traefik middleware is only **half** the wiring. It is inert until the
Authentik side exists.

**Half 1 — Traefik (already in place):**
- Reusable middleware lives at
  `Docker/Traefik/traefik/dynamic/authentik-forwardauth.yml` (middleware name
  `authentik`).
- Copy-paste example route at
  `Docker/Traefik/traefik/dynamic/_example-routes.yml` (a plain HTTPS service +
  the same one gated by `authentik`).
- To protect an app: add `- authentik` to its router's `middlewares:` list.

**Half 2 — Authentik (NOT done yet — do this before relying on the gate):**
1. Create a **Proxy Provider** (Providers → Create → *Proxy Provider*).
   - *Forward auth (single application)* for one host, **or**
   - *Forward auth (domain level)* with external host `https://sso.holy-grail.ch`
     and cookie domain `holy-grail.ch` to cover `*.holy-grail.ch` with one
     provider (cleaner for many apps).
2. Create an **Application** and bind it to that provider, bound to the
   `admin`/`streaming` groups as needed.
3. Assign the provider to the **embedded outpost** (Applications → Outposts →
   *authentik Embedded Outpost* → add the provider). The middleware in Traefik
   already points at this embedded outpost
   (`authentik-server:9000/outpost.goauthentik.io/auth/traefik`).
4. *(single-application mode only)* the protected host also needs a router for
   `/outpost.goauthentik.io/` → the `authentik` service, so the login
   redirect/callback works on that host. See the commented block in
   `_example-routes.yml`. Domain-level mode does **not** need this.

Until Half 2 exists, attaching the `authentik` middleware will make the auth
subrequest fail (≈400) and the route won't work — so wire the provider first.

> TODO / not yet built: the Proxy Provider + outpost binding above. When we
> want our first forward-auth-gated app, add it (ideally as a blueprint entry in
> `blueprints/mvp.yaml`, mirroring how the OIDC providers are declared).
