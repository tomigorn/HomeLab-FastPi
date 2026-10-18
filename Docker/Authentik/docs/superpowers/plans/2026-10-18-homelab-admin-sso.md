# Homelab admin SSO: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Six admin tools sign in through Authentik, gated to the group
`homelab-admins`. Each keeps one break-glass login.
Spec: `Docker/Authentik/docs/superpowers/specs/2026-10-18-homelab-admin-sso-design.md`.

**Architecture:** One idempotent `ak shell` provisioning script creates all
Authentik objects. A small helper writes the generated client secrets into each
project's gitignored `.env`, printing key names only. Each tool gets a LAN+VPN-only
`<name>.holy-grail.ch` Traefik router: `websecure`, `certResolver: cloudflare`,
first middleware `local-networks@file`.

**Tech stack:** Authentik 2026.8.4 (Django ORM via `ak shell`), Traefik v3 file
provider, Docker Compose, Grafana 13, Portainer CE 2.45.2, AdGuard Home
v0.107.74, wg-easy 15.4.0, Home Assistant 2026.10 + hass-oidc-auth v1.2.1.

---

## Ground rules (every task)

- **Repo and commits.**
  - The repo root is `/home/pi/Projects` and it is **public**. Never commit secrets.
  - Commit message: `Project Name: short description`, e.g.
    `Authentik: provision Grafana OIDC provider`, `Traefik: add grafana.holy-grail.ch route`.
  - **No** Co-Authored-By trailer or any AI attribution line.
- **Secrets.**
  - Never print secrets to the terminal and never put them in reports.
  - `.env` is gitignored and holds the real values. `.env.example` is identical to
    `.env` but with secret values blank: same keys, order and comments.
  - When reading config files that contain secrets, redact them, e.g.
    `sed 's/password:.*/password: <redacted>/'`.
- **Traefik.**
  - Dynamic config in `Docker/Traefik/traefik/dynamic/` hot-reloads; no restart.
  - After every change, check `docker logs traefik --since 2m 2>&1 | grep -i error`.
  - Traefik fails **closed**, so a broken file can take routes down.
  - Run `Docker/_global/scripts/smoke-test.sh` after each task. It must stay green,
    except for checks that already failed before the task.
- **Authentik shell.** `cd /home/pi/Projects/Docker/Authentik && docker compose exec -T server ak shell < <script>`.
- **Testing a new host from the LAN** (fastpi itself counts as 127.0.0.1/LAN):
  `curl -sk -o /dev/null -w '%{http_code} %{redirect_url}\n' --resolve <host>:443:192.168.1.2 https://<host>/`
- **Testing the internet path** must give 403 (the tunnel arrives as 172.24.0.1):
  `curl -s -o /dev/null -w '%{http_code}\n' https://<host>/ --resolve <host>:443:$(dig +short holy-grail.ch @1.1.1.1 | head -1)`
  - If the public name does not resolve, the result is a connection failure.
    Record that instead; it is also acceptable.
- **Users.** The Authentik user is `tomigorn` (email in Authentik; don't hardcode
  it in committed files — read it from Authentik at runtime). The group
  `homelab-admins` already exists, with tomigorn as a member.
- **Don't touch:** the `authentik@file` middleware's header list, Cloudflare,
  the Zyxel router.

---

### Task 1: Authentik provisioning script + secret helper + Traefik dashboard

**Files:**
- Create: `Docker/Authentik/scripts/provision-admin-sso.py`
- Create: `Docker/Authentik/scripts/apply-sso-env.py`
- Modify: `Docker/Traefik/traefik/dynamic/dashboard.yml`

- [ ] **Step 1: Write the provisioning script, dashboard part.**
  Model it on `Docker/Avatar-Picker/scripts/provision-authentik.py`, and copy flows
  from `ProxyProvider cup-proxy`.

  ```python
  # Idempotent Authentik setup for homelab admin SSO (spec 2026-10-18-homelab-admin-sso-design.md).
  # Run: docker compose -f Docker/Authentik/docker-compose.yaml exec -T server ak shell < this file \
  #        | python3 Docker/Authentik/scripts/apply-sso-env.py
  # Secrets leave only as "ENV <relative .env path> KEY=value" lines on stdout, which
  # apply-sso-env.py writes into gitignored .env files.
  from authentik.core.models import Application, Group
  from authentik.outposts.models import Outpost
  from authentik.policies.models import PolicyBinding
  from authentik.providers.proxy.models import ProxyMode, ProxyProvider

  admins = Group.objects.get(name="homelab-admins")
  src = ProxyProvider.objects.get(name="cup-proxy")
  outpost = Outpost.objects.get(name="authentik Embedded Outpost")

  def bind_admins(app):
      PolicyBinding.objects.get_or_create(target=app, group=admins, defaults={"order": 0})

  def app_for(slug, name, provider, url):
      app, _ = Application.objects.update_or_create(
          slug=slug, defaults={"name": name, "provider": provider, "meta_launch_url": url})
      bind_admins(app)
      return app

  def proxy(name, host, **extra):
      p, _ = ProxyProvider.objects.update_or_create(name=name, defaults={
          "mode": ProxyMode.FORWARD_SINGLE, "external_host": host,
          "authorization_flow": src.authorization_flow,
          "invalidation_flow": src.invalidation_flow, **extra})
      outpost.providers.add(p)
      return p

  # 1. Traefik dashboard
  app_for("traefik-dashboard", "Traefik dashboard",
          proxy("traefik-dashboard-proxy", "https://traefik.holy-grail.ch"),
          "https://traefik.holy-grail.ch/dashboard/")
  outpost.save()
  print("OK provisioned")
  ```
  Verify each import path against the running version (2026.8.4), e.g.
  `docker compose exec -T server ak shell -c "from authentik.policies.models import PolicyBinding; print('ok')"`,
  and adapt if a name moved.

- [ ] **Step 2: Write `apply-sso-env.py`.**
  It reads stdin. For each `ENV <path> <KEY>=<value>` line it upserts KEY in
  `/home/pi/Projects/Docker/<path>`: it replaces an existing `KEY=` line in place,
  or appends a line. It then prints `set <path> <KEY>` with no value. Any other
  line is passed through, unless it contains `SECRET`, `TOKEN` or `PASSWORD`; in
  that case it prints `[redacted line]`.
  - Refuse paths that are not `<dir>/.env` under Docker/, or that are tracked by git
    (`git ls-files --error-unmatch`).
  - Write atomically and keep the file mode.
  - Add a unit test, `Docker/Authentik/scripts/test_apply_sso_env.py` (pytest,
    using a tmp dir and an injectable base path): it covers upsert-replace, append,
    redaction and refusing a non-.env path.
  - Run `python3 -m pytest Docker/Authentik/scripts -q` and expect PASS.

- [ ] **Step 3: Run the provisioning script and expect `OK provisioned`.** Run it
  twice to prove it is idempotent: the second run must not create duplicates
  (check `PolicyBinding` count for the app == 1).

- [ ] **Step 4: Traefik routers.** Append to `dashboard.yml`, keeping the existing
  `dashboard` router and `dashboard-auth` as break-glass, and a comment saying so:

  ```yaml
      # SSO: https://traefik.holy-grail.ch - LAN+VPN only, Authentik group homelab-admins.
      # Break-glass when Authentik is down: the basicAuth router above (http://fastpi.homelab/dashboard/).
      traefik-dashboard-sso:
        rule: "Host(`traefik.holy-grail.ch`)"
        entryPoints: ["websecure"]
        priority: 10
        service: api@internal
        middlewares:
          - local-networks@file
          - authentik@file
          - traefik-dashboard-root
        tls:
          certResolver: cloudflare
      traefik-dashboard-sso-outpost:
        rule: "Host(`traefik.holy-grail.ch`) && PathPrefix(`/outpost.goauthentik.io/`)"
        entryPoints: ["websecure"]
        priority: 15
        service: authentik@file
        middlewares:
          - local-networks@file
        tls:
          certResolver: cloudflare
  ```
  Add a middleware, `traefik-dashboard-root`: a `redirectRegex` from
  `^https://traefik\.holy-grail\.ch/?$` to `https://traefik.holy-grail.ch/dashboard/`.
  Check how other files reference the authentik service (`authentik@file` is used
  in `avatar-picker.yml`).

- [ ] **Step 5: Verify.**
  - The certificate is issued (Traefik log shows no ACME error; the cert subject
    is checked with `openssl s_client`).
  - A LAN curl returns 302 to `sso.holy-grail.ch`.
  - The internet path returns 403.
  - The break-glass check without credentials,
    `curl -s -o /dev/null -w '%{http_code}' -H 'Host: fastpi.homelab' http://127.0.0.1:8080/dashboard/`,
    still returns 401.
  - `https://traefik.holy-grail.ch/outpost.goauthentik.io/ping` (or the start path)
    returns a non-404.

- [ ] **Step 6: Commit.**
  `Authentik: add admin SSO provisioning script` and `Traefik: add SSO dashboard route`.

### Task 2: Grafana

**Files:** `Docker/Authentik/scripts/provision-admin-sso.py`,
`Docker/grafana/docker-compose.yaml`, `Docker/grafana/.env`, `Docker/grafana/.env.example`,
create `Docker/Traefik/traefik/dynamic/grafana.yml`.

- [ ] **Step 1: Extend the provisioning script with an OAuth2 helper.**
  - Use `authentik.providers.oauth2.models`: `OAuth2Provider`, `ClientTypes`,
    `RedirectURI`, `RedirectURIMatchingMode`, `ScopeMapping`.
    - Check the field names in this version:
      `docker compose exec -T server ak shell -c "from authentik.providers.oauth2.models import OAuth2Provider; print([f.name for f in OAuth2Provider._meta.get_fields()])"`.
    - In 2026.x, `redirect_uris` is a list of `RedirectURI(matching_mode, url)`,
      and may carry a `redirect_uri_type` / authorization-vs-post-logout field.
      Match whatever the model has.
  - Settings:
    - The authorization flow and invalidation flow are copied from an existing
      OAuth2 provider, e.g. the Audiobookshelf or Jellyfin one; list them first.
    - `property_mappings` = the default `openid`, `email`, `profile` and
      `offline_access` scope mappings (`managed` ids `goauthentik.io/providers/oauth2/scope-*`).
    - `signing_key` = the existing default certificate (`authentik Self-signed Certificate`).
    - `sub_mode` = default.
  - Generate `client_id`/`client_secret` only on create. On rerun, keep the
    existing ones.
  - Always print `ENV grafana/.env GRAFANA_OAUTH_CLIENT_ID=...` and
    `ENV grafana/.env GRAFANA_OAUTH_CLIENT_SECRET=...`.
  - App slug `grafana`, launch URL `https://grafana.holy-grail.ch`, bind admins.
  - Confidential client. Redirect (strict) `https://grafana.holy-grail.ch/login/generic_oauth`.
    If the model supports a post-logout URI, add `https://grafana.holy-grail.ch/logout`.

- [ ] **Step 2: Run the script and confirm `.env` got both keys.** Add the same
  two keys, blank, to `.env.example`, in the same position and with a comment
  `# Authentik OIDC client (written by Authentik/scripts/provision-admin-sso.py)`.

- [ ] **Step 3: Compose env** on the grafana service, plus the
  `traefik_proxy` network (external, as other projects declare it; copy the
  `networks:` declaration style from `Docker/Portainer/docker-compose.yaml`), plus
  `extra_hosts: ["sso.holy-grail.ch:192.168.1.2"]`:

  ```yaml
        - GF_SERVER_ROOT_URL=https://grafana.holy-grail.ch
        - GF_AUTH_GENERIC_OAUTH_ENABLED=true
        - GF_AUTH_GENERIC_OAUTH_NAME=authentik
        - GF_AUTH_GENERIC_OAUTH_CLIENT_ID=${GRAFANA_OAUTH_CLIENT_ID}
        - GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET=${GRAFANA_OAUTH_CLIENT_SECRET}
        - GF_AUTH_GENERIC_OAUTH_SCOPES=openid profile email offline_access
        - GF_AUTH_GENERIC_OAUTH_AUTH_URL=https://sso.holy-grail.ch/application/o/authorize/
        - GF_AUTH_GENERIC_OAUTH_TOKEN_URL=https://sso.holy-grail.ch/application/o/token/
        - GF_AUTH_GENERIC_OAUTH_API_URL=https://sso.holy-grail.ch/application/o/userinfo/
        - GF_AUTH_GENERIC_OAUTH_USE_PKCE=true
        - GF_AUTH_GENERIC_OAUTH_USE_REFRESH_TOKEN=true
        - GF_AUTH_GENERIC_OAUTH_GROUPS_ATTRIBUTE_PATH=groups
        - GF_AUTH_GENERIC_OAUTH_ALLOWED_GROUPS=homelab-admins
        - GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH=contains(groups[*], 'homelab-admins') && 'GrafanaAdmin'
        - GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_STRICT=true
        - GF_AUTH_GENERIC_OAUTH_ALLOW_ASSIGN_GRAFANA_ADMIN=true
        - GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN=true
        - GF_AUTH_SIGNOUT_REDIRECT_URL=https://sso.holy-grail.ch/application/o/grafana/end-session/
        # Break-glass: local admin at https://grafana.holy-grail.ch/login?disableAutoLogin=true
        # (or LAN http://192.168.1.2:3001/login?disableAutoLogin=true). Keep the login form.
  ```
  - Before recreating, confirm the local Grafana admin is not called `tomigorn`
    and does not have the Authentik user's email:
    `curl -s -u admin:$GRAFANA_ADMIN_PASSWORD http://127.0.0.1:3001/api/users`,
    with the password read from `.env` into a variable, never echoed.
  - Check whether Grafana's root URL change breaks anything that uses `:3001`
    links. Alert links in Alertmanager or Telegram that point at Grafana are fine
    with the new URL.

- [ ] **Step 4: Traefik `grafana.yml`.** Router `grafana`: Host
  `grafana.holy-grail.ch`, websecure, cloudflare cert, middlewares
  `[local-networks@file]`, service → `http://grafana:3000`. Header comment
  explains the LAN-only + SSO + break-glass setup.

- [ ] **Step 5: Recreate and verify.**
  - `cd Docker/grafana && docker compose up -d grafana`.
  - `docker exec grafana wget -qO- https://sso.holy-grail.ch/application/o/grafana/.well-known/openid-configuration | head -c 200`
    shows the issuer.
  - A LAN `curl https://grafana.holy-grail.ch/login` gets a 302 to
    `sso.holy-grail.ch/application/o/authorize/` (auto-login).
  - `/login?disableAutoLogin=true` returns 200.
  - The local-admin API with basic auth still works.
  - Smoke test: update `_global/scripts/smoke-test.sh` if it checks Grafana by
    URL, and add a check that `grafana.holy-grail.ch` redirects to sso.

- [ ] **Step 6: Commit:** `Authentik: ...`, `Grafana: enable Authentik SSO`,
  `Traefik: add grafana.holy-grail.ch route`.

### Task 3: Portainer

**Files:** provisioning script, `Docker/Portainer/docker-compose.yaml`,
`.env`/`.env.example`, create `Docker/Traefik/traefik/dynamic/portainer.yml`.

- [ ] **Step 1: Provisioning.**
  - OAuth2 provider `portainer`, confidential.
  - Redirect (strict) `https://portainer.holy-grail.ch/`.
  - App slug `portainer`, bind admins.
  - Print `ENV Portainer/.env PORTAINER_OAUTH_CLIENT_ID=` / `..._SECRET=`.
  - Blank keys in `.env.example`. Also fix `.env.example`: its
    `PORTAINER_ADMIN_PASSWORD` currently holds a placeholder value, which must be
    blank.

- [ ] **Step 2: Traefik.**
  - Check which ports the container serves: `docker exec portainer ...`, or
    `docker inspect portainer` for ports (9000 http and/or 9443 https).
  - Prefer `http://portainer:9000` if it is enabled. Otherwise use
    `https://portainer:9443` with a `serversTransport` that has
    `insecureSkipVerify: true` (comment: self-signed backend inside the docker
    network).
  - Router Host `portainer.holy-grail.ch`, `[local-networks@file]`, cloudflare cert.
  - Portainer websockets (console) pass through Traefik natively.
  - Add `extra_hosts: ["sso.holy-grail.ch:192.168.1.2"]` to compose and recreate.

- [ ] **Step 3: Portainer API** (initial-admin password from `Portainer/.env`,
  never echoed). Admin username: try `admin`.
  1. `POST /api/auth` `{"username":"admin","password":...}` → jwt.
  2. `GET /api/users`. If no user `tomigorn` exists, create it with
     `POST /api/users` `{"username":"tomigorn","password":<random 40 chars, discarded>,"role":1}`.
     Role 1 = administrator. The random password is never used, because OAuth logs in.
  3. `GET /api/settings`, then `PUT /api/settings` with:
     - `AuthenticationMethod: 3` (OAuth)
     - `OAuthSettings`:
       - `ClientID` and `ClientSecret` from .env
       - `AuthorizationURI` `https://sso.holy-grail.ch/application/o/authorize/`
       - `AccessTokenURI` `.../token/`
       - `ResourceURI` `.../userinfo/`
       - `RedirectURI` `https://portainer.holy-grail.ch/`
       - `LogoutURI` `https://sso.holy-grail.ch/application/o/portainer/end-session/`
       - `UserIdentifier` `preferred_username`
       - `Scopes` `openid profile email`
       - `OAuthAutoCreateUsers: false`
       - `SSO: true`

     Keep the other settings fields as returned.
  4. **If the admin login fails, stop.** Report BLOCKED with the exact field list
     for a manual UI entry. Do not try to reset the password.

- [ ] **Step 4: Verify.**
  - `GET /api/settings/public` shows OAuth enabled and the login URI.
  - The initial admin can still `POST /api/auth`. This is the break-glass, and it
    must succeed while OAuth is on.
  - LAN `https://portainer.holy-grail.ch/` returns 200.
  - The internet path returns 403.
  - Smoke test is updated.

- [ ] **Step 5: Commit.**

### Task 4: AdGuard Home

**Files:** provisioning script, `Docker/Traefik/traefik/dynamic/authentik-forwardauth.yml`,
create `Docker/Traefik/traefik/dynamic/adguard.yml`, `Docker/adguard/conf/AdGuardHome.yaml`
(root-owned, gitignored? check `git check-ignore`; edit with sudo; container stopped).

- [ ] **Step 1: Check the facts.**
  - The web UI listens on `http.address: 0.0.0.0:3000` (host network).
    **Verify** with `ss -ltnp | grep -E ':3000|:3080'`. The compose comment
    mentioning 3080 may be stale; fix the comment if so.
  - Traefik reaches the host at `http://192.168.1.2:<port>`. Check
    `docker exec traefik wget -qO- -S http://192.168.1.2:<port>/ 2>&1 | head -3`.
    If it is blocked, use `host-gateway` via `extra_hosts` on Traefik.
- [ ] **Step 2: Create the dedicated AdGuard user.**
  1. Generate a 40-char random password in a shell variable.
  2. Get its bcrypt hash via `htpasswd -nbBC 10 "" "$PW" | cut -d: -f2`. If
     htpasswd is missing, use `docker run --rm httpd:alpine htpasswd ...`.
  3. Stop adguardhome (**DNS outage, keep it under 30 s**: prepare everything
     first).
  4. Back up the config to `conf/AdGuardHome.yaml.bak-2026-10-18`.
  5. Append to `users:` an entry `- name: authentik-proxy` with the hash.
  6. Start it and confirm DNS works (`dig @192.168.1.2 example.com +short`).

  The plaintext goes into Authentik in Step 3 only, never into a file in the repo.
- [ ] **Step 3: Provisioning.**
  - Proxy provider `adguard-proxy`, forward_single, external host
    `https://adguard.holy-grail.ch`.
  - `basic_auth_enabled=True`, `basic_auth_user_attribute="adguard_username"`,
    `basic_auth_password_attribute="adguard_password"`. Check the field names on
    `ProxyProvider`.
  - App `adguard`, bind admins.
  - Set the attributes on group `homelab-admins` (`group.attributes`) rather than
    on a single user, so every admin inherits them. Verify that Authentik reads
    group attributes for basic auth (user attributes merged with group
    attributes). If it does not, set them on the user `tomigorn`.
  - The script reads the password from the environment variable
    `ADGUARD_PROXY_PASSWORD`, passed via `docker compose exec -T -e ADGUARD_PROXY_PASSWORD server ak shell`.
    The script does nothing for AdGuard if it is unset, so reruns of the script do
    not wipe it.
- [ ] **Step 4: Traefik.**
  - In `authentik-forwardauth.yml`, add middleware `authentik-basic`: same as
    `authentik` plus `Authorization` in `authResponseHeaders`.
  - Add a comment explaining why it is separate (Traefik deletes listed headers
    from the request first, so adding it to the shared middleware would strip
    client Authorization headers everywhere).
  - In `adguard.yml`:
    - Router `adguard` with `[local-networks@file, authentik-basic@file]`.
    - An outpost companion router (prio higher, `[local-networks@file]`, service
      `authentik@file`).
    - Service `http://192.168.1.2:<port>`.
- [ ] **Step 5: Verify.**
  - LAN curl returns 302 to sso.
  - The internet path returns 403.
  - The break-glass, `curl http://192.168.1.2:<port>/control/status`, still
    answers 401/403 without credentials. The admin password works for the user;
    don't test it with credentials you don't have.
  - Using `authentik-proxy` with the generated password, `/control/status`
    returns 200, proving the injected creds are valid.
  - DNS still resolves.
- [ ] **Step 6: Commit** (Traefik files, provisioning script). Never commit
  `AdGuardHome.yaml` if it is tracked; check first, and report if it is.

### Task 5: wg-easy (stage 1)

**Files:** provisioning script, `Docker/WireguardVPN/docker-compose.yaml`,
`.env`/`.env.example`, `Docker/Traefik/traefik/dynamic/wg-easy.yml`, smoke test.

- [ ] **Step 1: Provisioning.**
  - New ScopeMapping `wg-easy email (verified)`, scope_name `email`, expression
    `return {"email": request.user.email, "email_verified": True}`.
  - OAuth2 provider `wg-easy`, confidential. Property mappings: openid, profile
    and the new email mapping (**not** the default email mapping).
  - Redirects (strict): `https://wg-easy.holy-grail.ch/api/auth/oidc/callback` and
    `https://wg-easy.holy-grail.ch/api/auth/oidc/link`.
  - App slug `wg-easy`, bind admins.
  - Print `ENV WireguardVPN/.env WG_EASY_OIDC_CLIENT_ID=` / `..._SECRET=`. Blank
    keys in `.env.example`.
- [ ] **Step 2: Compose.**
  - Add `extra_hosts: ["sso.holy-grail.ch:192.168.1.2"]` and this env:
    ```
    OAUTH_PROVIDERS=oidc
    OAUTH_OIDC_NAME=authentik
    OAUTH_OIDC_SERVER=https://sso.holy-grail.ch/application/o/wg-easy/
    OAUTH_OIDC_CLIENT_ID=${WG_EASY_OIDC_CLIENT_ID}
    OAUTH_OIDC_CLIENT_SECRET=${WG_EASY_OIDC_CLIENT_SECRET}
    OAUTH_AUTO_REGISTER=false
    OAUTH_AUTO_LAUNCH=oidc
    ```
  - Check these exact names against the wg-easy v15.4.0 source in
    `/tmp/claude-1000/-home-pi/d598f866-d42f-54e9-8cba-8ee004cb24d3/scratchpad/src/wg-easy`
    (`docs/content/advanced/config/external-authentication.md`, `src/server/utils/oauth.ts`).
  - **The pinned `ipv4_address 172.24.0.5` must stay**: `local-networks@file`
    depends on it.
  - **Recreating restarts the VPN.** Do it quickly, then verify with `wg show`
    inside the container that the interface is up.
- [ ] **Step 3: Traefik.** Replace both `wg-easy.fastpi.homelab` routers with one
  router: Host `wg-easy.holy-grail.ch`, websecure, cloudflare cert,
  `[local-networks@file]`. Update the header comment. Grep the repo for
  `wg-easy.fastpi.homelab` (homelab dashboard links, README, smoke test) and
  update every reference.
- [ ] **Step 4: Link the admin.**
  1. Read the Authentik user's email (`ak shell`, user tomigorn) into a variable.
  2. Through the wg-easy API, using Basic auth with the `.env` admin creds via
     `https://wg-easy.holy-grail.ch` (--resolve), update the admin user's email:
     find the endpoint in the source, e.g. `POST /api/me` with `{name,email}`.
  3. Confirm with `GET /api/me`.

  The user's first OIDC login then links automatically
  (`loginWithOAuth` matches by email).
- [ ] **Step 5: Verify.**
  - `docker logs` shows no OAuth config errors.
  - `GET https://wg-easy.holy-grail.ch/api/auth/oidc` (--resolve) returns a 302 to
    `sso.holy-grail.ch/application/o/authorize/` with `redirect_uri` =
    `https://wg-easy.holy-grail.ch/api/auth/oidc/callback`.
  - The internet path returns 403.
  - The VPN handshake still works (`wg show` latest-handshake for a peer, if any
    are active).
  - Smoke test is updated.
- [ ] **Step 6: Commit.** **Do not** set `DISABLE_PASSWORD_AUTH` yet; that is
  stage 2, after the user confirms.

### Task 6: Home Assistant

**Files:** provisioning script, `Docker/Home-Assistant/config/configuration.yaml`
(root-owned; sudo), `Docker/Home-Assistant/config/custom_components/auth_oidc/`
(check gitignore; committing the vendored component is fine if the repo commits
config-as-code; follow what `.gitignore` says), `secrets.yaml` if needed,
create `Docker/Traefik/traefik/dynamic/home-assistant.yml`, README.

- [ ] **Step 1: Provisioning.**
  - OAuth2 provider `home-assistant`, **public** client (no secret).
  - Redirect (strict) `https://ha.holy-grail.ch/auth/oidc/callback`.
  - Scopes openid, profile, email.
  - App slug `home-assistant`, bind admins.
  - Print `ENV Home-Assistant/.env HA_OIDC_CLIENT_ID=` only if that project has
    an `.env`. Otherwise just print the client id; it is not a secret for a public
    client.
- [ ] **Step 2: Download the release zip.**
  - URL: `https://github.com/christiaangoossens/hass-oidc-auth/releases/download/v1.2.1/hass-oidc-auth.zip`.
  - Put it in a new empty dir in the scratchpad.
  - Compare its sha256 against the release's published digest, if GitHub shows
    one (`gh api repos/christiaangoossens/hass-oidc-auth/releases/tags/v1.2.1`
    → assets[].digest).
  - Unzip it into another new empty dir.
  - Check the content: `manifest.json` version 1.2.1, domain `auth_oidc`.
  - Copy it to `config/custom_components/auth_oidc/` with sudo, using the same
    ownership as `config/`.
- [ ] **Step 3: Config.**
  - Add to configuration.yaml:
    ```yaml
    http:
      use_x_forwarded_for: true
      trusted_proxies:
        - 172.24.0.0/16   # Traefik on traefik_proxy (the host sees the bridge address)
    auth_oidc:
      client_id: "<client id>"
      discovery_url: "https://sso.holy-grail.ch/application/o/home-assistant/.well-known/openid-configuration"
      display_name: "authentik"
      roles:
        admin: homelab-admins
        user: homelab-admins
      features:
        default_redirect: true
        automatic_person_creation: true
    ```
  - **Check the actual source IP HA sees from Traefik before choosing
    trusted_proxies.** HA logs a 400 "received X-Forwarded-For header from an
    untrusted proxy" if it is wrong. Prefer the narrowest range that works, e.g.
    the `traefik_proxy` gateway `/32` if that is what HA sees.
  - Check the config option names against the plugin's `docs/configuration.md`
    in the scratchpad clone.
  - Validate with `docker exec homeassistant python -m homeassistant --script check_config -c /config`
    (adapt the container name).
- [ ] **Step 4: Traefik `home-assistant.yml`.** Host `ha.holy-grail.ch`, websecure,
  cloudflare cert, `[local-networks@file]`, service `http://192.168.1.2:8123`.
  Websockets work natively.
- [ ] **Step 5: Restart HA and verify.**
  - The HA log shows `auth_oidc` loaded with no errors.
  - `https://ha.holy-grail.ch/` (--resolve) returns 200.
  - `/auth/oidc/welcome` (or the plugin's start path) returns 200 or a redirect to
    sso.
  - `http://192.168.1.2:8123/` still returns 200 (Companion apps).
  - The internet path returns 403.
  - The myStrom plug entities still update (no restart regressions).
- [ ] **Step 6: README section** "Authentik SSO": owner account = break-glass,
  never linked; `/?skip_oidc_redirect=true`; roles set at first login only.
  Then commit.

### Task 7: Docs + smoke test + stage-2 checklist

- [ ] `Docker/Authentik/README.md`: a section "Admin SSO (homelab-admins)" with a
  table of the six tools (host, method, break-glass) and how to rerun the
  provisioning script.
- [ ] The smoke test has one check per new host (LAN redirect/200) plus each
  break-glass check. Run it and expect everything green.
- [ ] Stage 2 is written into the README as a pending checklist: wg-easy
  `DISABLE_PASSWORD_AUTH=true` + `.env` cleanup after the user confirms login.
- [ ] Commit `Authentik: document admin SSO`.

### Stage 2 (controller, after the user confirms SSO logins)

- wg-easy:
  1. Set `DISABLE_PASSWORD_AUTH=true` in compose, with a comment giving the
     break-glass (set false + `docker compose up -d`).
  2. Remove `WG_EASY_ADMIN_PASSWORD` from `.env` and `.env.example` after
     grepping for consumers.
  3. Recreate the container.
  4. Verify that `POST /api/auth/password` is rejected.
  5. Commit.
