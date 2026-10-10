# Authentik SSO for the beefy media stack

**Goal:** Authentik is the only login. No app keeps its own user database or login
form, for the arr apps or for Jellyfin.

**Status 2026-10-06:** the Traefik half is written and committed. The Authentik half
cannot be done from the repo — Authentik keeps its configuration in PostgreSQL, not
in files — so §2 below is a manual checklist. Nothing is live yet: all new route
files are parked as `*.yml.disabled`.

---

## 0. The two honest caveats

**Jellyfin cannot use forward auth.** Its native clients (Android TV, Fire TV, iOS,
Android, Kodi) are not browsers: they cannot render a login page, follow an OAuth
redirect, or hold a session cookie. Putting `authentik@file` on the Jellyfin router
breaks every non-browser client immediately — and the web UI keeps working, so it
looks like a client bug rather than a proxy decision. Authentik's own docs say to
integrate Jellyfin by OIDC instead. That is what §3 does.

Consequence: **"no local login at all" is achievable for the arr apps but not fully
for Jellyfin.** Jellyfin always retains one local admin account that cannot be
deleted, and native apps still authenticate against Jellyfin's own endpoint. What is
achievable: every *human* account is an Authentik account, and the local admin
becomes a break-glass credential with a long random password, written down offline.

**These are public admin UIs.** Radarr, Prowlarr, Bazarr, qBittorrent and SABnzbd
are configured as public hostnames behind Authentik, because the brief was "Authentik
is the login everywhere" and Authentik here is invite-only with mandatory MFA. The
more conservative option — and the usual advice for arr admin interfaces, which have
a history of RCEs — is to make them LAN + WireGuard only. That is a one-line change
per service: replace

```yaml
      tls:
        certResolver: cloudflare
```

with `tls: {}`, rename the host to `<app>.fastpi.homelab`, add an `ipAllowList`
middleware copied from `beefy-wol.yml`, and skip the Cloudflare DNS record. Keep the
Authentik middleware either way — defence in depth.

---

## 1. What is already built (Traefik, committed)

| File | Purpose |
|---|---|
| `dynamic/authentik-forwardauth.yml` | the shared `authentik@file` forwardAuth middleware (**active**) |
| `dynamic/radarr.yml.disabled` | Radarr route, Authentik-gated |
| `dynamic/prowlarr.yml.disabled` | Prowlarr route |
| `dynamic/bazarr.yml.disabled` | Bazarr route |
| `dynamic/qbittorrent.yml.disabled` | qBittorrent route |
| `dynamic/sabnzbd.yml.disabled` | SABnzbd route |
| `dynamic/jellyfin.yml.disabled` | Jellyfin route — **no** forwardAuth, by design |

Two design points baked in:

- **Authentik runs before the wake gate.** `middlewares: [authentik@file, <app>-wake, …]`
  — order is execution order. beefy powers itself off when idle and the wake gate
  sends a WoL packet, so if the gate ran first, any anonymous stranger could boot a
  ~28W machine on demand. Authenticating first means only a logged-in user can.
  Jellyfin is the unavoidable exception (see §0).
- **Each host has a second router for `/outpost.goauthentik.io/`** with no
  middlewares and `priority: 10`. The login flow redirects the browser to that path
  on the *protected* host, so it must reach Authentik rather than the app. Omitting
  it is the most common way to produce a redirect loop that looks like "Authentik is
  broken".

**Why everything is parked:** Traefik requests a certificate the instant a router
appears. With no DNS record, ACME fails repeatedly, and Let's Encrypt rate-limits
failed validations per hostname. Rename each file to `.yml` only *after* its DNS
record exists.

---

## 2. Authentik objects to create — YOUR checklist

All of this is in the Authentik admin UI at `https://sso.holy-grail.ch/if/admin/`.
Authentik version in use: **5.2.14**.

### 2.1 One Proxy Provider + Application per arr app

Repeat for each of: `radarr`, `prowlarr`, `bazarr`, `qbittorrent`, `sabnzbd`.

1. **Applications → Providers → Create → Proxy Provider**
   - Name: `radarr-proxy`
   - Authorization flow: your usual explicit-consent or implicit flow
   - **Forward auth (single application)** ← not "Proxy", not "Forward auth (domain level)"
   - External host: `https://radarr.holy-grail.ch`
2. **Applications → Applications → Create**
   - Name: `Radarr`, slug `radarr`
   - Provider: `radarr-proxy`
   - Launch URL: `https://radarr.holy-grail.ch`
3. **Bind a group** so this is not open to every Authentik user:
   Application → Policy/Group/User Bindings → Bind group → e.g. a new
   `media-admins` group. This mirrors the existing `streaming-users` /
   `streaming-admins` pattern already used for Audiobookshelf.
4. **Applications → Outposts → `authentik Embedded Outpost` → Edit →** add the new
   application to its list. **This step is the one people forget**, and without it
   `/outpost.goauthentik.io/auth/traefik` returns **404** and the route is dead.

Single-application providers are used deliberately rather than one domain-level
provider: access here is gated per app by group, and a domain-level provider
collapses that into a single all-or-nothing application.

**Verification that the outpost is wired** (run on fastpi):

**This recipe does not work — do not use it.** Measured 2026-10-09: it returns
404 with no Host header and 500 with one, for a provider that is correctly
assigned and working. The embedded outpost selects the provider by the request's
host and needs the full set of `X-Forwarded-*` headers Traefik normally supplies,
so a bare wget cannot tell "not assigned" from "assigned and fine".

Test from outside instead, and compare against a route known to work:

```bash
# Expect 302 -> sso.holy-grail.ch, with the app's OWN client_id
curl -sk -o /dev/null -w '%{http_code} %{redirect_url}\n' https://<app>.holy-grail.ch/

# Expect 200 and a login page, identical in shape to a working app's
curl -skL -c /tmp/j -b /tmp/j -o /tmp/p.html \
  -w '%{http_code} %{url_effective}\n' https://<app>.holy-grail.ch/
grep -o '<title>[^<]*' /tmp/p.html
```

A 302 that then dead-ends in **400 "invalid, or mismatching redirection URI"**
means the provider exists but its `redirect_uris` are empty. That happens when
the provider was created straight through the Django ORM: the UI and REST API
call `ProxyProvider.set_oauth_defaults()` on save, which derives the redirect
URIs from `external_host`, and a raw `objects.create()` does not. Fix:

```python
p = ProxyProvider.objects.get(name="<app>-proxy"); p.set_oauth_defaults(); p.save()
```

### 2.2 Jellyfin — an OAuth2/OpenID provider, not a proxy provider

1. **Providers → Create → OAuth2/OpenID Provider**
   - Name: `jellyfin-oidc`
   - Client type: **Confidential**
   - Redirect URI: `https://jellyfin.holy-grail.ch/sso/OID/redirect/authentik`
   - Signing key: your default certificate
   - Note the **Client ID** and **Client Secret**
2. **Applications → Create** → `Jellyfin`, slug `jellyfin`, provider `jellyfin-oidc`
3. Bind a group (e.g. `media-users`)

---

## 3. App-side settings — what actually removes the local login

**Status: all applied and verified 2026-10-09.** Values below are what is
actually set on beefy, read back from each app rather than from memory.

| App | Setting | Value | Verified |
|---|---|---|---|
| **Radarr** | Settings → General → Security → Authentication | **External** | `authenticationMethod=external` |
| **Prowlarr** | Settings → General → Security → Authentication | **External** | `authenticationMethod=external` |
| **Bazarr** | Settings → General → Security → Authentication | **None** | `auth.type: null` |
| **qBittorrent** | Options → WebUI → Bypass auth for whitelisted subnets | `172.28.10.0/24` | `AuthSubnetWhitelistEnabled=true` |
| **SABnzbd** | Config → General → Security → username/password | leave **empty** | both `""`, `inet_exposure=0` |
| **SABnzbd** | Config → General → Host whitelist | add `sabnzbd.holy-grail.ch` | `sabnzbd, sabnzbd.holy-grail.ch, 192.168.1.102` |

Two corrections to what this document originally said:

- **The qBittorrent subnet was wrong here.** It said `172.24.0.0/16`; the stack's
  bridge network is `172.28.10.0/24`. The running config was always correct — it
  was this table that was wrong, which is the more dangerous direction: a reader
  "fixing" the app to match the doc would have broken the bypass and locked
  Traefik out.
- **Radarr and Prowlarr sat on `none`, not `external`, until 2026-10-09.** Both
  disable the app's own login, so nothing was exposed — the public path was
  always behind Authentik and the LAN path behind the `DOCKER-USER` rule. But
  `none` is the legacy value and makes newer Servarr releases nag that
  authentication is disabled, which teaches you to ignore their health panel.
  Changed via `PUT /api/v3/config/host`; both apps restart themselves on an auth
  change, and the public routes were re-checked afterwards (still 302 to
  `sso.holy-grail.ch`, Traefik still reaching them on the LAN).

Servarr's **External** authentication method exists precisely for reverse-proxy
auth — it is the supported path, not a hack. Do **not** also leave Forms auth on:
two login prompts in series is not defence in depth, it is just friction that tempts
you into disabling the wrong one later.

**Do not blank qBittorrent's password.** Its WebUI is also published on beefy's LAN
port 8080, which does not pass through Traefik or Authentik. The whitelist approach
keeps the LAN port protected while letting the proxy through. For the same reason,
consider dropping the host port publications from the compose file once these routes
are live — otherwise every app has an unauthenticated LAN back door.

**API keys are unaffected.** Radarr↔Prowlarr↔qBittorrent↔SABnzbd all talk over
beefy's own Docker network, never through Traefik, so no inter-app integration
passes this gate.

### Jellyfin SSO plugin

1. Dashboard → Plugins → Repositories → add
   `https://raw.githubusercontent.com/9p4/jellyfin-plugin-sso/manifest-release/manifest.json`
2. Catalogue → **SSO Authentication** → install → restart Jellyfin
3. Dashboard → Plugins → SSO-Auth → add an OID provider:
   - Name `authentik`
   - Endpoint `https://sso.holy-grail.ch/application/o/jellyfin/`
   - Client ID / Secret from §2.2
   - Enable **Enabled**, **Enable Authorization by Plugin**, and set role claim
     `groups` if you want group-based admin mapping
4. Test at `https://jellyfin.holy-grail.ch/SSOViews/linking` before relying on it
5. Only then reduce the local admin to a long random break-glass password

---

## 4. Cloudflare — DNS and tunnel ingress (YOUR step)

Six new hostnames: `radarr`, `prowlarr`, `bazarr`, `qbittorrent`, `sabnzbd`,
`jellyfin` — all `.holy-grail.ch`.

The tunnel runs with `--token-file`, i.e. it is **dashboard-managed**: ingress rules
live in the Cloudflare UI, not in this repo, so they cannot be added from here. If a
wildcard `*.holy-grail.ch` ingress → Traefik already exists, only the DNS records
are needed; otherwise add an ingress entry per hostname.

**Order matters:** create DNS first, *then* rename the `.yml.disabled` files. Doing
it the other way round means Traefik fails ACME in a loop and can hit Let's
Encrypt's failed-validation rate limit.

---

## 5. Bring-up order

1. Cloudflare DNS (+ ingress if no wildcard) for all six hostnames
2. Authentik providers, applications, group bindings, **and the embedded-outpost
   assignment** (§2)
3. Deploy the beefy stacks (see `MEDIA-STACK-TODO.md` on beefy for its own
   prerequisites — the Docker boot-order drop-in first of all)
4. Set each app's auth method to External/None (§3)
5. `mv <app>.yml.disabled <app>.yml` on fastpi — one at a time, verifying each
6. Verify, per host:
   ```bash
   # should 302 to sso.holy-grail.ch, NOT 404 and NOT the app itself
   curl -sk -o /dev/null -w '%{http_code} -> %{redirect_url}\n' \
     --resolve radarr.holy-grail.ch:443:127.0.0.1 https://radarr.holy-grail.ch/
   ```
7. Confirm the blackbox probes pick them up (add the new hostnames to
   `grafana/prometheus/prometheus.yml`, `blackbox-public` job)

## 6. Rollback

`mv <app>.yml <app>.yml.disabled` — Traefik watches the directory and drops the
router within a second. No restart, and no effect on any other route.
