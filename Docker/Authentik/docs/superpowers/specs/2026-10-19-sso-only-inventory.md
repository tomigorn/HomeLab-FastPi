# SSO-only inventory: every login surface in the homelab

Date: 2026-10-18/19. Status: research input for a design (read-only; nothing was changed).

Requirement (user, verbatim): "actually all programs, we need to disable local user login and only
ever allow authentik/holy grail sso login".

Working interpretation:

- Every web UI offers **only** Authentik ("Holy Grail") SSO. No username/password form that works
  over the network (internet, LAN or VPN).
- Recovery when Authentik is down happens **from a server shell only**: flip an env flag and
  restart, run a CLI reset, or open an ssh tunnel to a port bound to localhost.
- Machine/API access (API keys, tokens, agents, scrapers, refresh tokens) is not a "user login".
  It must keep working, and it is listed per app.

How this was gathered:

- `docker ps` and `ss -ltn` on fastpi.
- Every compose file under `Docker/`, every Traefik dynamic file, and the READMEs.
- Live read-only probes (HTTP status codes, public `/status` endpoints).
- Upstream source for wg-easy 15.4.0, hass-oidc-auth 1.2.1, Portainer 2.45.2 and Audiobookshelf
  2.37.1 (local clones in the session scratchpad). Home Assistant 2026.10.0 was read inside the
  running container.
- Upstream docs and source for the rest, via research subagents.

beefy and tower were **asleep** and were not woken. Their rows come from fastpi's Traefik files,
the repo docs and upstream docs.

No secrets, passwords or email addresses are in this file; only key names.

---

## 0. Key facts that shape the design

1. **The edge.**
   - Public traffic arrives as Cloudflare tunnel, then `cloudflared`, then Traefik `websecure`;
     its source IP is the docker gateway 172.24.0.1.
   - LAN clients hit 192.168.1.2:443 directly.
   - VPN clients arrive NATed as 172.24.0.5 (wg-easy).
   - `local-networks@file` = 127.0.0.1, ::1, 192.168.1.0/24 and 172.24.0.5.
   - The `traefik_proxy` bridge is **172.24.0.0/16, gateway 172.24.0.1**, and Traefik is
     172.24.0.3 (not pinned).
2. **Direct host ports bypass Traefik and SSO.** Many apps publish a port on `0.0.0.0` of fastpi
   (see section 2). Each one is a login surface, or an *unauthenticated* surface, that SSO never
   sees. Making things "SSO-only" is as much about closing these ports as about app settings.
3. **There is an existing "hard deny" pattern** in `nextcloud.yml`: an `ipAllowList` whose only
   range is TEST-NET-1 `192.0.2.1/32` (middleware `nextcloud-deny`). It already blocks
   `?direct=1` and `POST /login` on `cloud.holy-grail.ch`. The same pattern blocks a single login
   endpoint for Portainer and others. It is best promoted to a shared `deny@file` middleware.
4. **No Home Assistant Companion app is logged in today.**
   - `.storage/auth` holds only browser refresh tokens: 4 owner tokens via the homeassistant
     provider, with client ids `http://192.168.1.2:8123/` and `http://fastpi.homelab:8123/`, and
     1 OIDC-user token.
   - There are no `https://home-assistant.io/{iOS,android}` clients and no `mobile_app` config
     entries.
   - So removing the HA password provider breaks no Companion app *today*. Read 2026-10-18.
5. **wg-easy's admin is already OIDC-linked.** In the wg-easy DB, `users_table` has one admin with
   `oauth_provider` set and no TOTP. `DISABLE_PASSWORD_AUTH=true` cannot lock it out.
6. **Audiobookshelf is already SSO-only.**
   - Public `/status` reports `authMethods: ["openid"]`.
   - A dummy `POST /login` returns 500, because the local passport strategy is not registered.
7. Login surfaces that are **not web** (noted only): SSH and Samba (section 4).

---

## 1. Inventory table

Legend for **Proposed method**:

- **N** = native setting
- **P** = Traefik path block (deny middleware)
- **L** = bind the host port to 127.0.0.1, or remove it
- **F** = put `authentik@file` forward auth in front, and the app trusts the proxy or has no login
- **X** = not possible natively; workaround given

### 1a. fastpi: the six admin tools (SSO today, break-glass to remove)

| App | Where | Reached via | User login today | SSO today | Can local login be disabled natively? (evidence) | Proposed method | Machine/API clients that must keep working | Shell recovery | Risk / user action |
|---|---|---|---|---|---|---|---|---|---|
| **Traefik dashboard** | fastpi, `traefik` | `traefik.holy-grail.ch` (local-networks + `authentik@file`); `fastpi.homelab` `/api` + `/dashboard` on the `internal` entrypoint `:8080`, basicAuth `dashboard.users` | basicAuth (break-glass router `dashboard`) | yes (forward auth) | n/a: the basicAuth is our own router | **Delete** router `dashboard`, middleware `dashboard-auth` and file `dashboard.users` | Prometheus scrapes `192.168.1.2:8080/metrics`. That is the separate `prometheus@internal` router created by `metrics.prometheus.entryPoint: internal`; it is **not** the `dashboard` router and is unaffected. Nothing else uses `/api` or `/dashboard`: grepped the repo and the landing page. | `docker exec traefik wget -qO- http://127.0.0.1:8080/api/http/routers` does not work once the router is gone (nothing serves `/api`). Instead, temporarily drop a router file back into `dynamic/` (file provider `watch: true`, no restart), or read `docker logs traefik` and the access log. | Low. `smoke-test.sh` check "traefik break-glass (401)" must become an expect-404 check. |
| **Grafana** (grafana-oss latest = 13.x) | fastpi, `grafana` | `grafana.holy-grail.ch` (local-networks, native generic OAuth); host **`0.0.0.0:3001`** | login form (`admin`, `GF_SECURITY_ADMIN_PASSWORD`); Basic auth on the API | yes (generic OAuth, auto-login) | **Yes.** `GF_AUTH_DISABLE_LOGIN_FORM=true` *unregisters* the Form client: `POST /login` returns 400 "client not configured: form" (`pkg/services/authn/authnimpl/registration.go`, `service.go`). `GF_AUTH_BASIC_ENABLED=false` unregisters the Basic client. Optional `GF_AUTH_DISABLE_LOGIN=true` also unregisters the internal password client. Docs: grafana.com configure-grafana `[auth]`, `[auth.basic]`. | **N + L**: set `GF_AUTH_DISABLE_LOGIN_FORM=true` and `GF_AUTH_BASIC_ENABLED=false`; publish `127.0.0.1:3001:3000` (Traefik uses `grafana:3000` on traefik_proxy). Drop the `disableAutoLogin` break-glass comments. | No repo script uses Grafana Basic auth or the admin password (grepped). `smoke-test.sh` uses `http://127.0.0.1:3001/api/health`, which is unauthenticated and still works on 127.0.0.1. Service-account tokens (`Bearer glsa_…`) keep working; the APIKey client is always registered. Provisioning is file-based (no API). | Set `GF_AUTH_DISABLE_LOGIN_FORM=false` in compose, `docker compose up -d`, then `ssh -L 3001:127.0.0.1:3001 fastpi` and log in as admin. Lost password: `docker exec grafana grafana cli admin reset-admin-password <pw>`. `GF_SECURITY_ADMIN_PASSWORD` applies only at first DB creation. | Low. Update the "grafana break-glass form" smoke check. Keep `GRAFANA_ADMIN_PASSWORD` in `.env` as the recorded recovery password. |
| **Portainer CE 2.45.2** | fastpi, `portainer` | `portainer.holy-grail.ch` (local-networks, native OAuth "Custom") to `portainer:9000`; host **`0.0.0.0:9443`** | internal auth: in OAuth mode **only user ID 1** (the initial admin) may `POST /api/auth`; everyone else gets 422 (`api/http/handler/auth/authenticate.go:97-103`, `isUserInitialAdmin`) | yes (OAuth) | **No in CE.** "Hide internal authentication prompt" (`HideInternalAuth`) is BE-only: `FeatureId.HIDE_INTERNAL_AUTH` maps to `Edition.BE` (`app/react/portainer/feature-flags/feature-flags.service.ts`); the CE controller returns early when `isLimitedToBE`; the CE backend `OAuthSettings` struct has no such field. | **P + L**. Traefik router on `portainer.holy-grail.ch` with `PathRegexp(`^/api/+auth/?$`) && Method(`POST`)` → deny, at higher priority. This is exactly the password login; `/api/auth/oauth/validate` and `/api/auth/logout` are separate exact mux routes and still work (`handler.go:41-46`). Then publish `127.0.0.1:9443:9443`. | **Agent on beefy**: Portainer dials out to the agent on :9001 with signed headers, so the block has no effect. API keys (`X-API-Key`) are per-request and unaffected. `smoke-test.sh` uses `https://127.0.0.1:9443/api/status` and `/api/settings/public`, which keep working on 127.0.0.1. | `ssh -L 9443:127.0.0.1:9443 fastpi`, then `https://localhost:9443/#!/internal-auth` as the initial admin; the Traefik rule does not apply to that path. Lost password: stop the container, then `docker run --rm -v portainer_data:/data portainer/helper-reset-password` (resets user ID 1). | Low-medium. **Residual:** any container on `traefik_proxy` can still reach `portainer:9000` directly and POST `/api/auth`. That is the internal network, not LAN/VPN/internet, and it is acceptable. A stronger fix would be Portainer BE, or moving the Portainer↔Traefik link to a dedicated network. |
| **AdGuard Home** (latest) | fastpi, `adguardhome`, **host network** | `adguard.holy-grail.ch` (local-networks + `authentik-basic@file`, which injects Basic for user `authentik-proxy`); host **`*:3000`** (`http.address: 0.0.0.0:3000`) | own login: `users:` `admin` (human) and `authentik-proxy` (machine, injected by Authentik) | yes (forward auth + injected Basic) | No SSO or header-auth mode. But **users can be removed from `users:`**; it is a plain list, and keeping only `authentik-proxy` leaves no human password. | **N + L-ish**: (1) delete the `admin` entry from `users:` in `conf/AdGuardHome.yaml`, keeping `authentik-proxy` (its password exists only as a bcrypt hash in YAML and as group attributes in Authentik); (2) set `http.address: 172.24.0.1:3000` so it is no longer on the LAN interface. Traefik (172.24.0.3) reaches it and the backend URL becomes `http://172.24.0.1:3000`. | DNS on :53 is unaffected. Nothing in the repo calls `/control/*` except `smoke-test.sh` ("adguard break-glass (401)" on `192.168.1.2:3000`), which must change. HA has no AdGuard integration (checked config entries). | Stop the container, add a user with a bcrypt hash to `users:` (or restore `0.0.0.0:3000`), start it, then `ssh -L 3000:172.24.0.1:3000 fastpi`. | **Medium; read carefully.** (a) Binding 172.24.0.1 is **not** a hard boundary: VPN clients (routed through wg-easy, whose gateway is 172.24.0.1), every container on traefik_proxy, and a LAN host that adds a static route via 192.168.1.2 can still reach 172.24.0.1:3000. The real control is (1): no human password exists. (b) **AdGuard is the LAN/VPN DNS**: if 172.24.0.1 is missing at boot (bridge not yet up), the HTTP listener fails, and AdGuard may exit, taking DNS down. Test with a reboot, and keep the old line as a one-line rollback. Option (1) alone is already "no human local login"; (2) is a hardening extra. |
| **wg-easy 15.4.0** | fastpi, `WireGuard-VPN` | `wg-easy.holy-grail.ch` (local-networks, native OIDC); no host UI port | password (`/api/auth/password`, plus `Authorization: Basic` on the API) | yes (OIDC, `OAUTH_AUTO_LAUNCH=oidc`) | **Yes.** With `DISABLE_PASSWORD_AUTH=true`, `api/auth/password.post.ts` returns 403 and `utils/session.ts getCurrentUser` returns 403 for any `Authorization` header; `methods.get.ts` reports `passwordDisabled`. Docs: `docs/content/advanced/config/external-authentication.md`. | **N**: add `DISABLE_PASSWORD_AUTH=true` and recreate. Remove `WG_EASY_ADMIN_PASSWORD` (and the v14 `PASSWORD_HASH`/`HOST_DOMAIN`) from `.env`/`.env.example`. | WireGuard itself (UDP 51820, key-based) is unaffected. No scraper uses the wg-easy API (no Prometheus job). | Set `DISABLE_PASSWORD_AUTH=false`, `docker compose up -d`, then `/login?auto_launch=false`. The password still lives in the DB; if forgotten, reset it via wg-easy's CLI/DB per its docs. | **Low.** First OIDC login links by email independently of the flag: `Database.users.loginWithOAuth` (`server/database/repositories/user/service.ts:311-371`) finds the user by `(oauthProvider, oauthId)`, else **by email**, then sets the link. It never checks `DISABLE_PASSWORD_AUTH`. TOTP (if enabled) still works via `/login/2fa` (`verify-2fa.post.ts` has no password-flag check). **And the admin is already linked** (DB check above). |
| **Home Assistant 2026.10.0** + hass-oidc-auth 1.2.1 | fastpi, `homeassistant`, **host network** | `ha.holy-grail.ch` (local-networks, OIDC component); host **`0.0.0.0:8123`** (LAN; this is the URL in README for Companion apps) | `homeassistant` provider (implicit default; no `auth_providers:` in YAML) for the owner; `auth_oidc` for the OIDC admin | yes (`default_redirect: true`; backup via `?skip_oidc_redirect=true`) | **Yes, by core config:** `homeassistant: auth_providers: []` is accepted. The schema is `EnsureList` with only `insecure_example` forbidden (`core_config.py:291`). The default `[{"type":"homeassistant"}]` applies only when the key is absent (line 369). hass-oidc-auth then registers itself as the only provider (`__init__.py _register_oidc_provider`) and its docs recommend this to skip the welcome screen (`docs/configuration.md` "Skipping the welcome screen", discussion #67). The plugin itself has no "hide password" switch. | **N**: add `auth_providers: []` under `homeassistant:` and restart. | **Long-lived access tokens keep working**: they have `credential=None`, and `_async_resolve_provider` returns None (`auth/__init__.py:620-650`). The InfluxDB integration (HA → `127.0.0.1:8086`) is outbound, so unaffected. **Refresh tokens bound to homeassistant credentials die**: the next refresh raises `InvalidProvider`, so those browsers are logged out within about 30 minutes. Today these are only the 4 owner browser tokens. | Re-add `auth_providers: [{type: homeassistant}]` (or delete the key) and restart. Lost password: `docker exec -it homeassistant hass --script auth --config /config change_password <user> <pw>`; the script hard-codes the homeassistant provider. | **Medium; user action.** (a) The **owner account** becomes unusable for login. It stays owner in the store, and the OIDC admin (`system-admin`) does everything day-to-day. Alternatively, link the owner first: set `automatic_user_linking: true` temporarily and log in via SSO with a matching username, then turn it off again (docs warn it bypasses MFA). (b) **Companion apps** must use **`https://ha.holy-grail.ch`** (LAN/VPN only), not `http://192.168.1.2:8123`. On mobile the plugin uses a **device-code** flow: the app shows a code, and you approve it in Safari/Chrome at ha.holy-grail.ch after the Authentik login (`docs/faq.md:53-65`, `endpoints/welcome.py` `is_mobile` from client_id `https://home-assistant.io/…`). The IP URL could still display the code, but approval must happen on the hostname (strict redirect). (c) Port 8123 stays on the LAN (Companion LAN access, Cast), but the password form there is gone. Note: http settings live in `.storage/http` (`trusted_proxies 172.24.0.0/16`), not YAML. That range also covers wg-easy 172.24.0.5, so VPN clients that hit `192.168.1.2:8123` directly are "trusted proxies" and could spoof `X-Forwarded-For` (this affects ip_ban only, not login). |

### 1b. fastpi: other apps and surfaces

| App | Where | Reached via | User login today | SSO today | Native disable? | Proposed method | Machine/API clients | Shell recovery | Risk / user action |
|---|---|---|---|---|---|---|---|---|---|
| **Audiobookshelf 2.37.1** | fastpi `audiobookshelf` (beefy migration planned) | `audiobookshelf.holy-grail.ch` (public, no forward auth); no host port | **none left**: `authActiveAuthMethods=["openid"]` (live `/status`) | yes (native OIDC) | **Yes, already done.** The local strategy is loaded only if listed (`server/Auth.js:111-120`); `POST /login` returns 500 (probed). | **N (done)**. Nothing to change. Optionally set `authOpenIDAutoLaunch` (currently false). | Mobile app: native OpenID with PKCE, redirect `audiobookshelf://oauth`; it hides the password form when `local` is absent. JWT bearer and API keys (Settings → API Keys) are always loaded (`Auth.js:122`). | **No env var.** Stop the container, back up `absdatabase.sqlite`, then edit table `settings` row `server-settings`: add `"local"` to `authActiveAuthMethods`. Blanking any OIDC field also makes it fall back to `local` at the next start (`ServerSettings.js:178-188`). The host sqlite3 is too old for this DB schema; use a current sqlite3 image. | Low. Caveat: ABS **fails open to `local`** if its OIDC settings become *invalid*. That needs DB access, so it is acceptable. |
| **Claude-Mockups** (Caddy) + answer-inbox | fastpi `claude-mockups`, `claude-mockups-inbox` | `claude-mockups.holy-grail.ch` (public; Traefik rate limit + headers); no host port | Caddy `basic_auth` (shared user, bcrypt `BASIC_AUTH_HASH`) | no | n/a: our own Caddyfile | **F**: add `authentik@file` + an outpost companion router (pattern in `cup.yml`); create a `proxy()` provider/app in `provision-admin-sso.py`, bound to the group the user is in; delete the `basic_auth` block from `Caddyfile`, drop `BASIC_AUTH_*` from `.env`/`.env.example` and `set-password.sh`. | **answer-inbox POST `/_inbox/submit`**: `assets/answer.js` does `fetch('/_inbox/submit', {method:'POST', credentials:'same-origin'})`. Same origin, so the Authentik proxy session cookie rides along and forward auth returns 200. Only if the Authentik session expires while the page is open does the fetch get a cross-origin 302 and fail; reload the page. `wait-for-answer.sh` reads files on disk, so it is unaffected. Blackbox `http_public` accepts 302, so it is fine. | Re-add the `basic_auth` block (hash in `.env`) and recreate, or `docker exec` / read `www/` directly. | Low. The user is remote: Authentik is public, so fine. Update the CLAUDE.md wording ("shared basic-auth login") and the `smoke-test.sh` check "claude-mockups (auth) 401" to expect a redirect to sso. |
| **LoyaltyCards PWA** + **LoyaltyCards-Sync** (PocketBase v0.39.1) | fastpi `loyalty-cards`, `loyalty-sync` | `loyalty-cards.holy-grail.ch` (static PWA, no login of its own); `loyalty-sync.holy-grail.ch` (PocketBase API + admin dashboard `/_/`, public) | `users` collection: email/password + mandatory TOTP (custom `/api/loyalty/totp/login`; `guards.go` blocks the standard password endpoint), Google OAuth2 (configured, not enabled); open signup ON; **superuser dashboard `/_/` is public** | no | See section 3.9: PocketBase supports generic OIDC providers and `passwordAuth.enabled=false` per auth collection. `_superusers` login is password (+OTP/MFA) only. | **N + code + P**: (1) add Authentik as an OIDC provider on `users`, set `passwordAuth.enabled=false`, disable signup except via OAuth2; (2) PWA: replace the email/password/TOTP UI with "Sign in with Holy Grail" (`pb.collection('users').authWithOAuth2({provider:'oidc'})`). Needs a new Authentik OIDC app; redirect `https://loyalty-sync.holy-grail.ch/api/oauth2-redirect`. (3) `superuser ips 127.0.0.1/32` (built-in `SuperuserIPs`) + Traefik deny for `/_/`, `/api/collections/_superusers/*` and `/api/collections/pbc_3142635823/*` (P); admin via ssh tunnel. The Authentik OIDC app needs the `email_verified: True` scope mapping. | PWA tokens (~3 years, Bearer) keep working for existing sessions. Linking existing accounts by email on first OAuth2 login: see section 3.9. Who uses it? If non-homelab people have accounts, they need Authentik accounts (invite-only enrollment). | `superuser upsert` CLI inside the container; re-enable `passwordAuth` in the dashboard via ssh tunnel. | **Medium; code change + user action.** This is an app with per-user data, and it is the only one needing a frontend change. Decide who its users are. |
| **Stonks** | fastpi `stonks` | `stonks.holy-grail.ch` (public); no host port | own single-user form login (`APP_USERNAME`/`APP_PASSWORD_HASH`, FastAPI `app/web/routes.py` `/login`) | no | No option to turn the login off (it is our own code). | **F + code**: add `authentik@file` + an outpost router, and add an app setting such as `AUTH_MODE=proxy` that trusts `X-authentik-username` (only reachable via Traefik: no host port, but restrict it to requests from Traefik) and removes `/login`. Keep form login behind an env flag for recovery. | Telegram bot is outbound only. | Flip the env flag back to form login and recreate. | Low; small code change in `~/Documents/development/Stonks`. |
| **Cup v3.5.1** | fastpi `Cup` | `cup.holy-grail.ch` (`authentik@file`); host **`0.0.0.0:8000` with NO auth** (probe: 200) | none (Cup has no auth) | forward auth on the hostname only | n/a | **L**: drop the host port. The Prometheus job `cup` and json-exporter use `http://192.168.1.2:8000/api/v3/json`; move them to `Cup:8000` (attach prometheus/json-exporter to a shared network) or bind `172.24.0.1:8000`. | Prometheus/json-exporter (see left); beefy's Cup agent is outbound from Cup. | n/a | Low. Today the full image inventory is readable unauthenticated from LAN/VPN. |
| **Avatar picker** | fastpi `avatar-picker` | `avatars.holy-grail.ch` (`authentik@file` + shared-secret header); `sso.holy-grail.ch/avatar-img/*` (local-networks, images only) | none | yes | n/a | Nothing to do. | Jellyfin and Nextcloud fetch avatar images from the LAN. | n/a | none |
| **Homelab dashboard** (nginx static) | fastpi `homelab-dashboard` | `home.holy-grail.ch` (public); `home.fastpi.homelab` (internal entrypoint); host **`0.0.0.0:8095`** | none (public link page) | n/a | n/a | Nothing (no login). Optional: drop host port 8095 (Traefik uses the container name). It links a dead `bitwarden.holy-grail.ch` and the retired `languagetool.holy-grail.ch`. | none | n/a | none |
| **BackdropCarousel** | fastpi | `backdrop-carousel.holy-grail.ch` (public images) | none | n/a | n/a | Nothing (no login by design). | Consumers fetch images. | n/a | none |
| **LanguageTool 6.8** | fastpi `languagetool` | `lang-tool.ddns.net` only via per-person secret token paths (`languagetool-token.yml`); no bare door | none (token-in-URL) | no | n/a | Out of scope: this is a **machine API** for browser add-ons, which cannot do OIDC. Keep the tokens. | browser add-ons | n/a | Note only. |
| **InfluxDB 2.9.1** | fastpi `influxdb` | host **`0.0.0.0:8086`** (UI + API); no Traefik route | UI username/password (`admin`) + API tokens | no | See section 3.10 (no SSO in OSS). | **L**: publish `127.0.0.1:8086:8086`. HA uses `127.0.0.1:8086` (host network); Telegraf and Grafana use `influxdb:8086`. The UI is then reachable only via ssh tunnel; the API is used with tokens only. | Telegraf (`INFLUX_TOKEN`), Grafana datasource (`GRAFANA_INFLUX_TOKEN`), HA influxdb integration (token, `127.0.0.1`), `smoke-test.sh` `/health` on 127.0.0.1. | `ssh -L 8086:127.0.0.1:8086 fastpi` and log in; `influx` CLI inside the container. | Low. |
| **Prometheus** | fastpi `prometheus` | host **`0.0.0.0:9090`** (no auth; probe 302 to /query) | none | no | No auth except `web.config.file` basic auth (section 3.10). | **L**: `127.0.0.1:9090:9090`. Grafana uses the internal network. | Grafana datasource; `smoke-test.sh` (127.0.0.1). | ssh tunnel | Low. It is an unauthenticated LAN read surface rather than a login. |
| **Alertmanager v0.34.1** | fastpi | host **`0.0.0.0:9093`** (no auth; probe 200) | none | no | same as Prometheus | **L**: `127.0.0.1:9093:9093`. | Prometheus uses `alertmanager:9093`; `smoke-test.sh` uses 127.0.0.1. | ssh tunnel | Low. Today anyone on LAN/VPN can create silences. |
| **blackbox-exporter, node-exporter, json-exporter, telegraf** | fastpi | no host ports | none | n/a | n/a | Nothing. | | | none |
| **CrowdSec** | fastpi `crowdsec` | no host port; LAPI `crowdsec:8080` internal (bouncer key file) | none (no web UI; console not used) | n/a | n/a | Nothing. | Traefik bouncer (LAPI key) | `cscli` | none |
| **Authentik itself** | fastpi | `sso.holy-grail.ch` | Authentik's own login: identification + password + mandatory MFA | it *is* the IdP | n/a | Out of scope: the IdP's own password + MFA login is the "Holy Grail SSO". | all OIDC/proxy clients | `ak` CLI in the container (`docker compose exec server ak create_recovery_key …`) | none |
| **Port-updater web** (mouse) | fastpi `port_updater` | host **`0.0.0.0:8087`** (probe 401) | Basic auth `WEB_USER`/`WEB_PASS` (`port-updater/web-server.py:310`) | no | Our own code: if `WEB_USER`/`WEB_PASS` are empty, auth is off. | **L** (bind `127.0.0.1:8087`), or **F** (Traefik route + `authentik@file`, blank the Basic creds, bind `172.24.0.1`). | none (status page) | ssh tunnel | Low. |
| **qBittorrent (fastpi seedbox, `qbittorrent_mouse`)** | fastpi, in gluetun netns | host **`0.0.0.0:8085`** via gluetun; no Traefik route | WebUI password (`WebUI\Password_PBKDF2`) | no | **No** switch to disable the form; `WebUI\AuthSubnetWhitelist(Enabled)` bypasses it for listed subnets (`src/webui/webapplication.cpp isAuthNeeded`). | **F + L**: add a Traefik route `qbittorrent-fastpi.holy-grail.ch` (local-networks + `authentik@file`), enable whitelist bypass for the source Traefik appears as, and remove the `8085` host port. Simpler alternative: **L only** (bind `127.0.0.1:8085`; use an ssh tunnel when needed). | **port_updater** logs in via `/api/v2/auth/login` with `QBIT_PASS` from `gluetun_IP:8080`, inside the network. Keep the password, or add that subnet to the whitelist. qBittorrent 5.2 also accepts a `WebUI\APIKey` bearer. | Edit `qBittorrent.conf` while stopped. | Low-medium. The password must stay set as a machine credential (port_updater), so the "no form over the network" goal is met by not exposing the port. |
| **SABnzbd (fastpi, `nzb` stack)** | fastpi, in gluetun_nzb netns | host **`0.0.0.0:8090`** (probe 403: `inet_exposure=0`); no Traefik route | username/password set | no | **Yes**: a blank username/password means no login (`interface.py check_login`). | **L** (bind `127.0.0.1:8090`), or **F** like the beefy one (blank creds + forward auth + host whitelist). | its API key (if any client uses it) | Edit `sabnzbd.ini` | Low. Check whether this instance is still needed now that beefy has SABnzbd. |
| **Mousehole** | fastpi, in gluetun netns | host **`0.0.0.0:5010`** (probe 302 to its login) | Mousehole ≥0.5 password (`MOUSEHOLE_AUTH_PASSWORD`; it refuses to start without auth) | no | see section 3.10 | **L**: bind `127.0.0.1:5010`. `smoke-test.sh` uses `192.168.1.2:5010/health`; change it to 127.0.0.1. Optional F via a Traefik route. | MAM cookie refresh is outbound. | ssh tunnel | Low. |
| **M4B merge dashboard** (Caddy) | fastpi `m4b-merge-dashboard` | `192.168.1.2:8099` (LAN only by design) | none | no | n/a | **F or L**: either keep it LAN-only (it has no login, so it is not a "local login") or put it behind `m4b.holy-grail.ch` + `authentik@file` and bind `172.24.0.1`/127.0.0.1. | none | n/a | Decision for the user. It is an unauthenticated surface, not a login. |
| **Beefy-Waker / Tower-Waker** pages | fastpi, host network | `192.168.1.2:9001` / `:9002`; `beefy-wol.fastpi.homelab` / `tower-wol.fastpi.homelab` (local-networks); `/beefy-wake`, `/tower-wake` behind `authentik@file` | none | partly | n/a | Nothing (no login). Optional: put the `*-wol` hosts behind `authentik@file`. | Traefik forward-auth gates call `/gate` on 9001/9002, so these must stay reachable from Traefik. | n/a | none |
| **WG-Chores ("wg-aemtli")** + **sqlite-web** | fastpi `wg-chores-app` (dev repo `~/Documents/development/WG-Chores`), `wg-chores-sqliteweb` | `wg-aemtli.ddns.net` (public, LE); host **`0.0.0.0:8084`** (app) and **`0.0.0.0:8088`** (sqlite-web, **no auth**, probe 200) | none in the app (no auth code found); sqlite-web has no password | no | sqlite-web: only `--password` (section 3.10) | App: **F** only if the flatmates get Authentik accounts. Otherwise this is a deliberate public no-login app; mark it out of scope. sqlite-web: **L** (`127.0.0.1:8088`) or remove it. | none | n/a | **sqlite-web on :8088 gives anyone on LAN/VPN read/write access to the chores DB.** Close it regardless. |
| **Digitec price tracker** (web + pgweb + postgres) | fastpi (dev repo `~/Documents/development/Digitec-PriceTracker`) | host **`0.0.0.0:3002`** (web), **`0.0.0.0:8089`** (pgweb, **no auth**, probe 200), **`0.0.0.0:5432`** (postgres) | web: none; pgweb: none; postgres: password | no | pgweb: only `--auth-user/--auth-pass` (section 3.10) | **L** for all three (127.0.0.1), or **F** for the web UI via a Traefik route. Remove pgweb, or bind it to localhost. | none known | ssh tunnel | **pgweb on :8089 is an unauthenticated SQL console on the LAN.** Close it regardless. |
| **sbb-easyride-taxreport** | fastpi | host `0.0.0.0:8083` (did not answer on 127.0.0.1 during the probe) | unknown (no README read) | no | n/a | **L** or **F**. Check the app. | | | Low. |
| **Old LoyaltyCards .NET backend + CloudBeaver** | fastpi, compose in `/home/deploy/deployments/LoyaltyCards` (leftover of the wiped Flutter/.NET attempt) | host **`0.0.0.0:5000`** (backend), **`0.0.0.0:8978`** (CloudBeaver) | CloudBeaver local admin login | no | see section 3.10 | **Remove both containers** (stale), or **L**. | none (the PWA uses PocketBase now) | n/a | User decision: confirm they are dead before removing. |
| **go2rtc (HA)** | fastpi (inside HA) | `*:18555` (WebRTC media), API on 127.0.0.1:18554 | none | n/a | n/a | Nothing (media port, not a UI). | | | none |
| **CUPS** | fastpi host | 127.0.0.1:631 only | n/a | n/a | n/a | Nothing (localhost only). | | | none |
| **Not running** (compose present): HashiCorpVault (8200), Jenkins, bitwarden, `_Deprecated/*` | fastpi | none live | | | | If ever started again, they must follow the same rule. | | | Note only. |

### 1c. beefy (asleep; from Traefik files and docs)

| App | Reached via | User login today | SSO today | Native disable? | Proposed method | Machine/API | Recovery | Risk / action |
|---|---|---|---|---|---|---|---|---|
| **Jellyfin** | `jellyfin.holy-grail.ch`; LAN `192.168.1.102:8096` | being made SSO-only by another agent (OIDC plugin "Local password sign-in: Disable for all users", per `jellyfin.yml`) | yes | in progress | **in progress (other agent)** | native clients via Quick Connect | plugin setting via the DB/plugin XML | in progress |
| **Radarr** (stable v6.4) | `radarr.holy-grail.ch` (`authentik@file`); LAN `192.168.1.102:7878` | none: `AuthenticationMethod=External` (per `radarr.yml`; unverified while beefy sleeps) | forward auth | **Yes**: `External` = `NoAuthenticationHandler`, no login page (`AuthenticationBuilderExtensions.cs AddExternal`); env `RADARR__AUTH__METHOD`. Native OIDC (`Oidc=4`) exists only on Radarr `develop`/Sonarr v5 pre-release. | **N (done) + L**: verify `config.xml`. **The LAN port 7878 is open without any login** (External means no auth), which is an SSO bypass from LAN/VPN. Restrict the host port to fastpi only: firewall `DOCKER-USER` rule allowing only 192.168.1.2, or bind the port to beefy's LAN IP plus a rule. | Prowlarr, Bazarr, SABnzbd and qBittorrent talk over beefy's Docker network with `X-Api-Key`; unaffected. | edit `config.xml` | Medium: the LAN bypass. |
| **Prowlarr** (v2.6) | `prowlarr.holy-grail.ch` (`authentik@file`); LAN `:9696` | External (assumed, same pattern) | forward auth | same as Radarr | same: **N + L** | API keys | `config.xml` | verify on wake |
| **SABnzbd** (5.1) | `sabnzbd.holy-grail.ch` (`authentik@file`); LAN `:8081` | none (blank creds, per `sabnzbd.yml`) | forward auth | Yes: blank creds (`check_login`) | **N (done) + L** (LAN port is open without login) | API key/NZB key (`check_apikey`) | `sabnzbd.ini` | verify on wake |
| **qBittorrent** (beefy) | `qbittorrent.holy-grail.ch` (`authentik@file`); LAN `:8080` | password kept, bypassed for 192.168.1.2/32 and 172.28.10.0/24 | forward auth | No form switch; whitelist bypass only | **OK as is**: LAN port 8080 still demands the password. To meet "no form over the network", restrict 8080 to fastpi (firewall) or bind it to localhost + docker net. | gluetun port hook via localhost bypass; Radarr via the 172.28.10.0/24 whitelist | `qBittorrent.conf` | Low-medium. |
| **Bazarr** (1.6) | `bazarr.holy-grail.ch` (`authentik@file`); LAN `:6767` | none (`auth.type` None, per `bazarr.yml`) | forward auth | Yes (`auth.type: null`) | **N (done) + L** | `auth.apikey` | `config.yaml` | verify on wake |
| **Portainer agent** | `beefy:9001` | n/a (signed requests from Portainer) | n/a | n/a | Nothing; optionally firewall 9001 to fastpi only. | Portainer server | | none |
| **M4B / other beefy tools, Samba** | LAN | see the beefy repo | | | Same rule: LAN UI ports restricted to fastpi, UI via Traefik + `authentik@file`. Samba: note only. | | | verify on wake |

### 1d. tower (Unraid 7.x; off for a memory test; not checked live)

| App | Reached via | User login today | SSO today | Native disable? | Proposed method | Machine/API | Recovery | Risk / action |
|---|---|---|---|---|---|---|---|---|
| **Unraid webGUI** | LAN `192.168.1.101` (no Traefik route) | root password | none configured | **No.** Unraid 7.2+ has built-in OIDC SSO (Settings → Management Access → API → OIDC; redirect `http(s)://<unraid>/graphql/api/auth/oidc/callback`; docs.unraid.net/API/oidc-provider-setup), but the **password form stays beside the SSO buttons** and root cannot be removed. Forward auth is not supported; community hacks edit system files. | **X** → "**SSO offered + local root remains, LAN-only**". Optionally add Authentik as Unraid's OIDC provider so SSO is the normal path; keep root (strong password, password manager) as the only exception. Never publish it via Traefik. | Unraid API keys; tower flash backup over ssh (key) | console / ssh key (`ssh tower-direct`) | Accept as the documented exception. |
| **Nextcloud** (fresh reinstall soon; v34 today) | `cloud.holy-grail.ch` (public, tower-wake); LAN `192.168.1.101:8080` | user_oidc (Authentik) + local admin (`?direct=1`) | yes | **Partly.** `occ config:app:set --type=string --value=0 user_oidc allow_multiple_user_backends` auto-redirects `/login` to the IdP (with exactly one provider). But **`/login?direct=1` cannot be disabled by any setting**; `hide_login_form` is cosmetic (core `config.sample.php`). OIDC-provisioned users have no password (the user_oidc backend has no check-password), so only local DB accounts (the admin) can password-login. | **N + P (already on the public host) + user hygiene**: (1) `allow_multiple_user_backends=0`; (2) keep the existing `nextcloud-local-login-denied` router (blocks `?direct=1` and `POST /login` publicly; `/login/v2` and `/login/flow` stay open for clients); (3) make the first OIDC admin a member of `admin` (via the cloud-admins group mapping), then **`occ user:disable <localadmin>`**, so no local account can log in on the LAN port either. Optional: `token_auth_enforced => true`. | Desktop/mobile clients use Login Flow v2 through the browser, so SSO works and they get an app password. WebDAV app passwords. The blackbox probe `http://192.168.1.101:8080/login` expects a 302 to SSO. | **occ works from the shell without any login**: `docker exec -u www-data nextcloud php occ user:enable <admin>` / `user:resetpassword`, or set `allow_multiple_user_backends` back to 1, or `app:disable user_oidc`. The local admin is still needed as the install account, but disabled. | Low for the fresh install: build it in from day one. |

---

## 2. Host ports on fastpi that bypass Traefik (`ss -ltn`, 2026-10-18)

| Port | Service | Auth on it | Proposal |
|---|---|---|---|
| 22 | sshd | key only (`PasswordAuthentication no`, `PermitRootLogin without-password`) | keep (not web) |
| 53 | AdGuard DNS | n/a | keep |
| 80/443 | Traefik | per router | keep |
| 8080 | Traefik `internal` (dashboard basicAuth, `/metrics`, `home.fastpi.homelab`) | basicAuth on dashboard | remove the dashboard router; keep `/metrics` |
| 139/445 | Samba (mouse) | SMB users | keep (not web; note) |
| 3000 | AdGuard UI | admin + authentik-proxy | `admin` removed; bind 172.24.0.1 |
| 3001 | Grafana | form | 127.0.0.1 |
| 3002 | Digitec web | none | 127.0.0.1 or Traefik+SSO |
| 5000 | old LoyaltyCards .NET backend | ? | remove |
| 5010 | Mousehole | password | 127.0.0.1 |
| 5432 | Digitec postgres | password | 127.0.0.1 |
| 8000 | Cup | **none** | remove / internal |
| 8083 | sbb-easyride | ? | 127.0.0.1 |
| 8084 | WG-Chores app | none | keep only if needed (Traefik serves it) |
| 8085 | qBittorrent (fastpi) | password | 127.0.0.1 |
| 8086 | InfluxDB | form + tokens | 127.0.0.1 |
| 8087 | port-updater | Basic | 127.0.0.1 |
| 8088 | sqlite-web (WG-Chores) | **none** | 127.0.0.1 / remove |
| 8089 | pgweb (Digitec) | **none** | 127.0.0.1 / remove |
| 8090 | SABnzbd (fastpi) | password | 127.0.0.1 |
| 8095 | homelab dashboard | none (public page) | optional remove |
| 8099 (192.168.1.2) | M4B dashboard | none | user decision |
| 8123 | Home Assistant | password provider (until removed) | keep (Companion/LAN) once the provider is removed |
| 8978 | CloudBeaver (old) | local admin | remove |
| 9001/9002 (192.168.1.2) | beefy/tower waker | none | keep (wake gates) |
| 9090 | Prometheus | **none** | 127.0.0.1 |
| 9093 | Alertmanager | **none** | 127.0.0.1 |
| 9443 | Portainer | internal admin | 127.0.0.1 |
| 18555 | go2rtc WebRTC | n/a | keep |
| 51820/udp | WireGuard | keys | keep |

Docker note: a `127.0.0.1:` publish is still reachable from the host itself, so ssh tunnels and
`smoke-test.sh` keep working. Containers on bridge networks that today use `192.168.1.2:<port>`
(Prometheus → Cup :8000) must move to container names or to `172.24.0.1`.

---

## 3. Answers to the specific questions

### 3.1 Portainer CE 2.45

- **Can internal auth be disabled or hidden in CE? No.** `HideInternalAuth` is a BE feature:
  - `FeatureId.HIDE_INTERNAL_AUTH` maps to `Edition.BE`.
  - The CE UI toggle no-ops via `isLimitedToBE` (`oauth-settings.controller.js:94-99`).
  - The CE backend `OAuthSettings` has no such field.
- **What CE does enforce.** In OAuth mode, `POST /api/auth` only accepts the **initial admin
  (user ID 1)**; everyone else gets 422 (`authenticate.go:97-112`).
- **Traefik rule.** Routes (`api/http/handler/auth/handler.go:41-46`, gorilla mux, exact paths,
  POST only):
  - `POST /api/auth` is the password login (internal/LDAP).
  - `POST /api/auth/oauth/validate` is OAuth.
  - `POST /api/auth/logout` is logout.

  A rule `Host(`portainer.holy-grail.ch`) && PathRegexp(`^/api/+auth/?$`) && Method(`POST`)` that
  points at a deny middleware therefore blocks the password login and leaves OAuth and logout
  working. Use a higher priority than the main router.
  - The trailing slash does not route to `authenticate` (no StrictSlash).
  - Gorilla cleans `//` paths.
  - Traefik 3.7.15 sanitizes paths by default (`--entrypoints.<name>.http.sanitizepath`, default "true", confirmed via `traefik --help`).
- **Other JWT-minting paths.**
  - `POST /api/users/admin/init` returns 409 once any user exists.
  - `POST /api/users/{id}/tokens` needs an authenticated session.
  - `X-API-Key` is per-request and not a login.
- **Agents.** The standard agent on beefy is dialled by Portainer (port 9001, signed headers).
  Edge agents use `/api/endpoints/{id}/edge/*` and :8000. Neither is affected.
- **Bind 9443 to localhost? Yes.**
  - Compose `ports: ["127.0.0.1:9443:9443"]`.
  - Traefik uses `portainer:9000` on traefik_proxy and is unaffected.
  - `smoke-test.sh` already uses `https://127.0.0.1:9443`.
  - Recovery: `ssh -L 9443:127.0.0.1:9443 fastpi`, then `https://localhost:9443/#!/internal-auth`.
- **Lost admin password.**
  - `docker run --rm -v portainer_data:/data portainer/helper-reset-password` (container stopped);
    it resets user ID 1.
  - `--admin-password-file` only applies to an instance with no admin, so it is not a recovery
    tool.
- **Residual.** `portainer:9000` is reachable from other containers on traefik_proxy.

### 3.2 Grafana 13

- **`GF_AUTH_DISABLE_LOGIN_FORM=true` is server-enforced.** The Form authn client is not
  registered, so `POST /login` returns 400 "client not configured: form".
- **`GF_AUTH_BASIC_ENABLED=false`** removes `Authorization: Basic` user:password on the API.
- **`GF_AUTH_DISABLE_LOGIN=true`** (optional, undocumented) unregisters internal DB-user password
  auth entirely.
- **What keeps working:** OAuth, and service-account tokens. The APIKey client is always
  registered and also accepts Basic with user `api_key`.
- **Repo usage.** Nothing uses Grafana Basic auth or the admin password:
  - Grafana provisioning is file-based (datasource + dashboards).
  - `smoke-test.sh` only calls the unauthenticated `/api/health` on `127.0.0.1:3001`, plus the
    "break-glass form" check, which must be updated.
  - No cron job uses it.
- **What breaks:** only the break-glass login and that smoke check.
- **Recovery.**
  - Set `GF_AUTH_DISABLE_LOGIN_FORM=false`, recreate, then ssh tunnel to 127.0.0.1:3001.
  - Lost password: `docker exec grafana grafana cli admin reset-admin-password <pw>`.
  - `GF_SECURITY_ADMIN_PASSWORD` only seeds a brand-new DB.

### 3.3 AdGuard Home

- **Gateway.** The traefik_proxy gateway is **172.24.0.1** (`docker network inspect`).
- **Binding.** `http.address: 172.24.0.1:3000` makes the UI unreachable at `192.168.1.2:3000`. It
  is **still reachable** from:
  - VPN clients (they route via wg-easy into 172.24.0.0/16),
  - any container on traefik_proxy,
  - a LAN host with a static route to 172.24.0.0/16 via fastpi (Linux accepts packets for a
    local address on any interface).

  So it narrows the exposure but is not a boundary.
- **Can `admin` be removed? Yes.** `users:` is a list, so deleting the `admin` element leaves
  `authentik-proxy`.
  - Its password exists only as a bcrypt hash in the YAML and as Authentik group attributes
    (`adguard_username` / `adguard_password` on `homelab-admins`), so no human types it.
  - This is the actual "no local human login" control.
  - The UI keeps working via `authentik-basic@file`.
  - Remember AdGuard's lockout: 5 failures cause a 15-minute block (`auth_attempts`,
    `block_auth_min`).
- **Recovery.**
  - Stop the container.
  - Add a user with a bcrypt hash (`htpasswd -B -n`), or set `http.address` back to `0.0.0.0:3000`.
  - Start the container, then `ssh -L 3000:172.24.0.1:3000 fastpi`.
- **Risk.** AdGuard serves DNS for LAN and VPN, so test a reboot with the 172.24.0.1 bind, because
  an HTTP listener failure at boot could take DNS down. Recommendation:
  1. Do the user removal first (low risk).
  2. Then the bind as a separate, rebooted-and-verified step, or skip the bind.

### 3.4 wg-easy 15.4.0

- **Does `DISABLE_PASSWORD_AUTH=true` still allow the first OIDC login to link by email? Yes.**
  - `loginWithOAuth` (`server/database/repositories/user/service.ts:311-371`) matches by
    `(oauthProvider, oauthId)`, then **by email**, writes the link, and has no reference to the
    password flag.
  - The flag is only checked in `api/auth/password.post.ts` (403) and in `utils/session.ts`
    (Authorization header returns 403).
  - With `OAUTH_AUTO_REGISTER=false`, an unknown email is refused.
- The current admin is already linked. Only `email_verified` must be present: the custom Authentik
  scope mapping already exists (`utils/oauth.ts:242`).

### 3.5 Home Assistant 2026.10.0 + hass-oidc-auth 1.2.1

- **Hide or remove password login: yes, via core config.**
  - Add `homeassistant: auth_providers: []`.
  - hass-oidc-auth then becomes the only provider, and the welcome screen is skipped (plugin docs
    and discussion #67).
  - There is no plugin flag to hide the password form while keeping the provider.
- **Existing sessions.**
  - Refresh tokens whose credential is a homeassistant-provider credential fail on the next
    refresh with `InvalidProvider` (`auth/__init__.py:620-650`), so they are logged out within the
    access-token lifetime of about 30 minutes.
  - Long-lived access tokens survive (credential None).
  - **Today, only the 4 owner browser tokens are affected; no Companion app tokens exist.**
- **Owner account.**
  - It stays owner in the store but cannot log in, since no provider is left for its credential.
  - The OIDC user (system-admin) is a full admin.
  - Owner-only differences are negligible. If wanted, link the owner to Authentik first: enable
    `automatic_user_linking` temporarily (username match), then turn it off.
- **Companion apps afterwards.**
  - Set the server URL to **`https://ha.holy-grail.ch`** (LAN/VPN; AdGuard resolves it).
  - The login shows the plugin's **device code**; open the shown link or code in Safari/Chrome
    (`ha.holy-grail.ch`), sign in with Holy Grail, and the app links automatically.
  - The strict redirect `https://ha.holy-grail.ch/auth/oidc/callback` means approval must happen
    on that hostname.
  - The app's internal URL can stay `http://192.168.1.2:8123` for LAN, but the login itself must
    use the hostname. Recheck this when the user does it.
- **HA http settings** live in `.storage/http` (2026.10: `use_x_forwarded_for`,
  `trusted_proxies 172.24.0.0/16`), not YAML. No change is needed for SSO-only.
- **Recovery.**
  - Delete `auth_providers: []` (or set `[{type: homeassistant}]`) in `configuration.yaml`, then
    `docker restart homeassistant`.
  - Lost password: `hass --script auth --config /config change_password` inside the container.

### 3.6 Traefik dashboard

- Yes: delete the `dashboard` router, the `dashboard-auth` middleware and `dashboard.users`.
  - Monitoring scrapes `/metrics` via the automatic `prometheus@internal` router on the same
    entrypoint, which is unaffected.
  - The homelab dashboard does not link it.
  - The only consumer is `smoke-test.sh` line 38.
- The `traefik.holy-grail.ch` SSO router stays.

### 3.7 Audiobookshelf

- Already SSO-only (`authActiveAuthMethods=["openid"]`).
- **Mobile apps:** the official app supports OpenID (PKCE, `audiobookshelf://oauth`) and hides the
  password form.
- **Recovery:** edit the DB (`settings` → `server-settings` → add `"local"`); there is no env var.
  It falls back to local automatically if the OIDC config is *invalid*.

### 3.8 Nextcloud (fresh install)

1. Install user_oidc, configure the single Authentik provider, and run
   `occ config:app:set --type=string --value=0 user_oidc allow_multiple_user_backends`.
2. `/login?direct=1` **cannot** be disabled by any Nextcloud setting; `hide_login_form` is
   front-end only.
   - Publicly it is blocked by the existing Traefik router `nextcloud-local-login-denied`.
   - On the LAN port it is neutralised by `occ user:disable` on the local admin once an OIDC user
     holds admin.
3. Is the local admin needed for occ? **No.** occ runs as www-data from the shell without any
   login. Keep the install admin account only as a disabled recovery identity (`occ user:enable`).
4. Clients: Login Flow v2 (`/login/v2`, `/login/flow`) goes through the browser, so SSO works and
   they get an app password. `token_auth_enforced` is optional.

### 3.9 PocketBase (LoyaltyCards-Sync, v0.39.1)

Source: pocketbase v0.39.0 tag; master has the same logic.

- **Generic OIDC: yes.** Auth collections support providers `oidc`, `oidc2` and `oidc3`
  (`tools/auth/oidc.go`). Collection options:
  - `oauth2.enabled`
  - `oauth2.providers[]`, each with `{name, clientId, clientSecret, authURL, tokenURL, userInfoURL,
    displayName, pkce, extra}`
  - `oauth2.mappedFields`
  - `passwordAuth.enabled`, `otp.*`, `mfa.*` (docs: pocketbase.io/docs/api-collections/)
- **OAuth2-only users: yes.** With `passwordAuth.enabled=false`, `auth-with-password` returns 403
  (`apis/record_auth_with_password.go`).
- **Linking existing accounts.** `authWithOAuth2` resolves the record in this order
  (`apis/record_auth_with_oauth2.go` ~L115-140, L338-395):
  1. an existing external-auth link;
  2. the logged-in record;
  3. **an existing record with the same email**, which is then auto-linked.

  Existing password users keep their data.
- **Gotcha:** PocketBase uses the email only if `email_verified` is true. Since Authentik 2025.10,
  the default email mapping says `false`. The OIDC app therefore needs the same custom
  `email_verified: True` scope mapping that wg-easy already uses. Without it, linking never happens
  and new-user creation fails because `email` is required.
- **New users** are created subject to `users.createRule`, which defaults to `""` (anyone).
  Restrict it, or rely on the Authentik application binding.
- **`_superusers` (`/_/`): password (+OTP/MFA) only. OAuth2 is forced off**
  (`core/record_model_superusers.go` L87-105; docs: "OAuth2 is not supported as auth method for the
  `_superusers` collection").
- **Best control:** the built-in `SuperuserIPs` whitelist, set with
  `pocketbase superuser ips 127.0.0.1/32 ...`. It is enforced at superuser login and on every
  superuser-token request (`apis/middlewares.go` L306-324). It needs correct trusted-proxy (real
  IP) settings behind Traefik.
- **Additionally, a Traefik deny** for `/_/`, `/api/collections/_superusers/*` and
  `/api/collections/pbc_3142635823/*` (the deterministic `_superusers` id).
- **Recovery CLI:** `superuser upsert|create|update|delete|otp|ips`.

### 3.10 Other upstream facts

- **InfluxDB 2.x OSS: no SSO** (SSO exists only in Cloud Dedicated).
  - `--ui-disabled` / `INFLUXD_UI_DISABLED=true` removes the UI assets only; `/api/v2` and the
    tokens keep working.
  - `POST /api/v2/signin` is **always** registered and cannot be disabled
    (`http/platform_handler.go`, `session/http_server.go`).
  - So: bind 8086 to 127.0.0.1. Optionally also set `INFLUXD_UI_DISABLED=true`, using
    `influx`-CLI/token only and ssh-tunnel recovery by flipping it back.
- **Prometheus / Alertmanager:** the only built-in auth is `--web.config.file` (`basic_auth_users`,
  TLS). There is no OIDC. So bind them to 127.0.0.1.
- **pgweb:** only `--auth-user/--auth-pass` (Basic); `--log-forwarded-user` only logs.
- **CloudBeaver CE:**
  - Local, Anonymous and **Reverse proxy** header auth (`provider: reverseProxy`, `user-header`
    default `X-User`). OIDC is Enterprise only.
  - Local can be removed from `app.enabledAuthProviders`; recovery is to re-add `"local"` in
    `.cloudbeaver.runtime.conf`.
  - Moot here: the instance is a stale leftover; remove it.
- **sqlite-web:** a single shared `--password` only.
- **Mousehole (>=0.4):**
  - `MOUSEHOLE_AUTH_PASSWORD`: single shared password, browser login.
  - `MOUSEHOLE_AUTH_TOKEN`: Bearer for the API.
  - `MOUSEHOLE_INSECURE_ALLOW_NO_AUTH=true` turns auth off. It is mutually exclusive with the
    credential variables.

  So either bind 5010 to 127.0.0.1, or add Traefik + `authentik@file` with
  `MOUSEHOLE_INSECURE_ALLOW_NO_AUTH=true` and no LAN port. Not possible today, because the port
  must not stay on the LAN with auth off.

### 3.11 Servarr, qBittorrent, SABnzbd, Bazarr, LanguageTool, Mousehole, Cup

- **Radarr/Prowlarr:** `External` (per the Traefik file comments) means no own login; the API key
  is separate. Native OIDC exists only on develop/pre-release branches.
- **Bazarr:** `auth.type: null`, so no login.
- **SABnzbd:** blank creds, so no login; set `host_whitelist` to include the hostname.
- **qBittorrent:** no "disable form" option; it uses subnet-whitelist bypass for fastpi
  (192.168.1.2/32) and the arr network.

**Gap:** with no own login, beefy's LAN ports (7878, 9696, 8081, 6767; and 8096 for Jellyfin)
are **open without any authentication** from LAN/VPN. Close this with a beefy firewall rule in
`DOCKER-USER` allowing only 192.168.1.2 (and loopback/docker nets) to those ports. Verify the
`config.xml`/`config.yaml` values when beefy is next awake for other reasons.

- **LanguageTool:** token URLs, no login (machine API).
- **Cup:** no auth; the hostname has forward auth, but host port 8000 is open.
- **Mousehole:** own password on 5010 (LAN).

### 3.12 Claude-Mockups

- Yes, it can use `authentik@file`. Add a proxy provider + app in `provision-admin-sso.py`, and
  bind it to a group the user is in (homelab-admins).
- The `/_inbox/submit` POST is same-origin with `credentials: 'same-origin'`, so the Authentik
  proxy cookie is sent and it keeps working for a logged-in user.
- Edge case: an expired SSO session gives a fetch failure; reload the page.
- Follow-up edits:
  - the user's global CLAUDE.md wording ("shared basic-auth login"),
  - the README,
  - `set-password.sh` (obsolete),
  - `smoke-test.sh`.

### 3.13 LoyaltyCards

- The **PWA** has no server-side accounts; accounts live in **PocketBase** (`users` collection,
  per-user `cards` with owner rules).
- PocketBase can trust Authentik via its built-in **OIDC OAuth2 provider**. A proxy header is not
  an option; PocketBase does not do header auth.
- Proposed:
  1. Authentik OIDC app `loyalty-cards`.
  2. Enable OAuth2 on `users` with an OIDC provider.
  3. `passwordAuth.enabled=false`.
  4. PWA: replace the password/TOTP/signup UI with "Sign in with Holy Grail".
  5. Remove the custom TOTP routes later.
  6. Block `/_/` and the `_superusers` auth endpoints publicly; admin via ssh tunnel.
- Who the users are (homelab people only?) decides whether this is acceptable: Authentik
  enrollment is invite-only.

### 3.14 Unraid 7.3

- Built-in OIDC SSO exists since 7.2, but the root password form always remains. Forward auth is
  unsupported.
- Classification: **"SSO offered + local root remains; LAN-only (no Traefik route)"**, a
  documented exception. Optionally configure Authentik as its OIDC provider.

---

## 4. Not web (note only)

- **SSH**:
  - fastpi: keys only (`passwordauthentication no`, `permitrootlogin without-password`).
  - beefy and tower: key-based per memory (`ssh tower-direct` uses a key).
  - SSH is the recovery channel for everything above and must stay independent of Authentik.
- **Samba**: fastpi `samba` (mouse, host network 139/445; accounts `SAMBA_ACCOUNT_*`), and later
  beefy. SMB has no OIDC; local SMB users remain. Restrict it to the LAN (it already is).
- **WireGuard**: key-based, not a login.
- **PostgreSQL :5432** (Digitec): a DB password. Bind it to localhost.

---

## 5. "Not possible natively" list and workarounds

| App | Why not | Workaround |
|---|---|---|
| Portainer CE | `HideInternalAuth` is BE-only; the initial admin can always `POST /api/auth` | Traefik deny on `POST ^/api/+auth/?$` + bind 9443 to 127.0.0.1; recovery via ssh tunnel |
| AdGuard Home | no SSO/header auth | delete the human `admin` user; only the Authentik-injected `authentik-proxy` remains; optionally bind 172.24.0.1 |
| Nextcloud | `?direct=1` cannot be disabled | the existing public Traefik deny + `occ user:disable` on the local admin; occ for recovery |
| Unraid | root form always shown; no forward auth | exception: LAN-only, optional OIDC SSO, root stays |
| qBittorrent | no "disable form" | whitelist bypass for the proxy + do not expose the port (firewall / 127.0.0.1); the password stays as a machine credential |
| Stonks | own code, no proxy mode | forward auth + small code change (trust `X-authentik-username`, hide `/login`) |
| LoyaltyCards (PocketBase) | users need an OIDC button in the PWA; `_superusers` is password-only | OIDC provider on `users` + `passwordAuth` off + PWA change; Traefik deny for `/_/` and the superuser endpoints |
| InfluxDB, Prometheus, Alertmanager, pgweb, sqlite-web, CloudBeaver, Mousehole | no OIDC, or no auth at all | bind to 127.0.0.1 (ssh tunnel) or remove; forward auth only if a browser UI is really wanted |
| Servarr (stable) | no native OIDC (only `External`) | keep `External` + forward auth, **and** firewall the beefy LAN ports to fastpi |
| Home Assistant mobile | the apps cannot do direct OIDC | plugin device-code flow on `https://ha.holy-grail.ch` |

---

## 6. Proposed implementation order

### Batch A: Claude alone, low risk, no user action (fastpi)

1. **Traefik dashboard:** delete the `dashboard` router, `dashboard-auth` and `dashboard.users`.
   Update `smoke-test.sh`.
2. **wg-easy:** `DISABLE_PASSWORD_AUTH=true`, recreate. Remove `WG_EASY_ADMIN_PASSWORD` (and the
   v14 leftovers) from `.env`/`.env.example`. Verify `POST /api/auth/password` returns 403 and the
   OIDC login still works (the user does one login; the admin is already linked).
3. **Grafana:** `GF_AUTH_DISABLE_LOGIN_FORM=true`, `GF_AUTH_BASIC_ENABLED=false`, port
   `127.0.0.1:3001`. Update the smoke check.
4. **Portainer:** Traefik deny router for `POST ^/api/+auth/?$`; port `127.0.0.1:9443`. Verify the
   OAuth login and the beefy agent environment.
5. **Close unauthenticated or locally-authed host ports** by binding them to 127.0.0.1: InfluxDB
   8086, Prometheus 9090, Alertmanager 9093, port-updater 8087, Mousehole 5010, qBittorrent 8085,
   SABnzbd 8090. Fix `smoke-test.sh` URLs. Cup 8000: move the Prometheus/json-exporter target to an
   internal address first, then drop the port.
6. **AdGuard step 1:** remove the `admin` user (keep `authentik-proxy`). Verify the SSO UI and DNS.
   Update the smoke check.
7. Docs: update `Authentik/README.md` "Admin SSO", the per-file break-glass comments, and the
   project READMEs with the new shell-only recovery paths.

### Batch B: Claude, medium risk, needs verification or a reboot window

8. **AdGuard step 2 (optional):** `http.address: 172.24.0.1:3000` + Traefik backend
   `http://172.24.0.1:3000`. Reboot test, because DNS depends on it.
9. **Claude-Mockups → `authentik@file`:** provision proxy app, outpost router, remove Caddy
   basic_auth. Test the answer-inbox Confirm round-trip with the user once. Update the CLAUDE.md
   wording; that is the user's file, so propose the edit.
10. **Dev apps on fastpi:** bind or remove pgweb 8089, sqlite-web 8088, Digitec web 3002 /
    postgres 5432, sbb 8083. These live in `~/Documents/development/*` repos.

### Batch C: needs user decisions or action

11. **Home Assistant:** `auth_providers: []`. User actions:
    - decide on the owner (link or accept orphan),
    - re-login in browsers,
    - point Companion apps at `https://ha.holy-grail.ch` and use the device-code login.

    None are logged in today.
12. **Old LoyaltyCards .NET backend + CloudBeaver** (`/home/deploy/...`): the user confirms they are
    dead, then remove them.
13. **M4B dashboard, WG-Chores app, homelab-dashboard port:** the user decides between LAN-only
    no-auth and forward auth. The WG-Chores flatmates would need Authentik accounts.
14. **Stonks:** small code change (proxy-header mode) + forward auth.
15. **LoyaltyCards:** decide who the users are, then PocketBase OIDC + PWA change + superuser
    lockdown. This is the largest item.

### Batch D: other hosts, when awake for other reasons (never wake them for this)

16. **beefy:** verify `External`/None/blank-creds settings, and add `DOCKER-USER` firewall rules
    so the arr/SAB/qBit/Bazarr/Jellyfin LAN ports accept only fastpi (192.168.1.2). Jellyfin SSO
    is being finished by the other agent.
17. **tower / Nextcloud fresh install:**
    - `allow_multiple_user_backends=0`,
    - admin via the OIDC group,
    - `occ user:disable` on the install admin,
    - keep the Traefik `nextcloud-local-login-denied` router.

    Unraid: optional OIDC; root stays (documented exception).

### Explicit exceptions to record

- Authentik's own login (it is the IdP).
- Unraid root.
- SSH keys (the recovery channel).
- Samba users.
- LanguageTool token URLs and other machine credentials.
- `authentik-proxy` in AdGuard (machine credential injected by Authentik).
