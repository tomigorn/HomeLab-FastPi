# Service customizations (fastpi)

Everything changed on a service beyond its stock image: plugins, injected scripts, proxy overlays, hooks, settings set by script or API, DB edits, pinned images, route exceptions. Add a row in the same change that makes the customization.

| Run | Command |
|---|---|
| One project (name = compose dir) | `Docker/_global/scripts/post-update-check.sh <Project>` |
| Everything (about 25 s) | `Docker/_global/scripts/post-update-check.sh all` |
| List projects | `Docker/_global/scripts/post-update-check.sh --list` |
| Registry vs checks | `Docker/_global/scripts/test_post_update_check.sh` |

- Checks: `Docker/_global/post-update.d/<Project>.sh`, one `check <id> <regex> "<actual>"` per id below, read-only, no secret printed.
- `update-project.sh` and the nightly auto-update run the project's file after an update and roll back when a check fails ([UPDATE-RUNBOOK](_global/UPDATE-RUNBOOK.md)).
- After every update, by hand or automatic: run the project's check, fix or roll back before calling it done.

## Traefik

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Pinned tag, plugin test before a bump | `docker-compose.yaml`, `scripts/traefik-plugin-test.sh` | `update-project.sh Traefik pull` runs the test first | `traefik.version-pin`: traefik version → 3.7.17 | a new tag rejecting the plugins or the experimental block |
| Local plugins realip + crowdsec bouncer (no registry download) | `traefik/plugins-local/`, `experimental.localPlugins` in `traefik/traefik.yml` | `docker compose up -d` | `traefik.local-plugins`: "Plugins loaded" log line → crowdsec-bouncer, realip; `traefik.config-reload`: last reload success metric set | Yaegi changes: plugin fails to load, websecure invalid, every route 404 |
| Real client IP in X-Forwarded-For | `dynamic/real-ip.yml`, entrypoint middlewares | file reload | `traefik.real-ip`: spoofed XFF on the public sso path, Authentik logs the real IP → real | middleware order or forwardedHeaders semantics |
| CrowdSec bouncer, fail open | `dynamic/crowdsec.yml` | file reload | `traefik.crowdsec-bouncer`: CAPI IP / clean IP as Cf-Connecting-Ip → 403 200; `traefik.bouncer-fail-open`: crowdsecMode, updateMaxFailure → stream -1 | plugin API change |
| Pinned IP 10.24.15.3 on traefik_authentik (Authentik trusts only it) | `docker-compose.yaml` | `docker compose up -d` | `traefik.authentik-ip`: network IP → 10.24.15.3 | network recreated without ipv4_address |
| Forward auth + LAN/VPN-only gate | `dynamic/authentik-forwardauth.yml`, `dynamic/local-networks.yml` | file reload | `traefik.forward-auth`: dashboard → sso authorize; `traefik.local-networks`: admin host from a non-local container → 403 | ipAllowList / forwardAuth semantics |
| Password-login blocks (Portainer, Jellyfin, Nextcloud) | `dynamic/portainer.yml`, `jellyfin.yml`, `nextcloud.yml` | file reload | `traefik.portainer-password-block`: POST /api/auth → 403; `traefik.jellyfin-password-block`: two auth POSTs → 403 403 (beefy not woken); `traefik.nextcloud-login-block`: POST /login → 403 | PathRegexp or priority changes |
| Jellyfin web files: conditional request headers dropped (File Transformation keeps the old ETag, Cloudflare kept a stale bundle) | `dynamic/jellyfin.yml` router `jellyfin-web`, middleware `jellyfin-web-no-conditional` | file reload | `traefik.jellyfin-web-fresh`: bundle with its own ETag as If-None-Match → 200 (skipped while beefy sleeps) | router priority or headers semantics |
| Jellyfin stream URLs need a valid token (B-03: Jellyfin streams `?static=true` without one) | `dynamic/jellyfin.yml` router `jellyfin-stream`, middleware `jellyfin-stream-auth` → waker `/stream-auth` | file reload | `traefik.jellyfin-stream-auth`: anonymous stream URL → 401 (skipped while beefy sleeps) | Jellyfin stream path names, new token places in clients |
| Tracker allow-list + token-URL blocks | `dynamic/tracker.yml` | file reload | `traefik.tracker-allow-list`: unknown path, webhook POST → 404 403 | rule matcher changes |
| Tracker block of encoded `/` `\` `%` NUL in the path (Traefik matches the raw path, Django decodes it) | `dynamic/tracker.yml` router `tracker-blocked` | file reload | `traefik.tracker-encoded-block`: `/accounts/signup%2F`, `/details/image%5Cx` → 400 400 (entrypoint), `/accounts/signup%252F` → 403 (this router) | path matching on decoded vs raw path |
| Entrypoint `encodedCharacters` (S-02): websecure refuses encoded `/` `\` NUL, langtool (:8443) refuses all seven; `%25 %3B %3F %23` stay allowed on websecure (file names) | `traefik/traefik.yml` (static, restart) | `docker compose restart traefik` | `traefik.encoded-chars`: sso `/a%2Fb` → 400, sso `%23` → 404 (allowed, reaches Authentik), wg-aemtli `%3F` → 400 | Traefik changing the defaults or key names (3.6.4 → 3.6.7 did) |
| Seerr CSP enforced (S-16, since 2026-10-31): `script-src 'self'` without inline, TMDB/Plex/Gravatar images, YouTube frames | `dynamic/requests.yml` middleware `requests-secure-headers` | file reload | `traefik.requests-csp`: `enforced 1, report-only 0` | Seerr/Next.js adding inline scripts or new hosts breaks pages (known harmless violation: Zod 4 `Function("")` probe, so no `'unsafe-eval'`); re-test as in `Traefik/README.md` |
| LanguageTool preflight answered by Traefik, never by LT (bare OPTIONS = 404) | `dynamic/languagetool.yml` router `languagetool-preflight` → `noop@internal` | file reload | `traefik.lt-preflight`: bare OPTIONS, real preflight → 404 200 | CORS middleware preflight handling |
| LanguageTool token routers (gitignored) | `dynamic/languagetool-token.yml`, entrypoint :8443 | `LanguageTool/Raspi/scripts/lt-token.py add` | `traefik.lt-token-routers`: router count, first token, bare path → N routers, token 200, bare 404 (count only, never a token); `traefik.lt-token-quiet`: every token router and the `languagetool-preflight` router (its path carries the token) have `accessLogs: false` (S-07, A-24) and the token file keeps group 65026 (Traefik's uid) | entrypoint or ReplacePathRegex changes, observability schema |
| Metrics only on the internal entrypoint | `traefik/traefik.yml` | `docker compose up -d` | `traefik.metrics-internal`: LAN :8080, Prometheus scrape → 000 1 | entrypoint defaults |
| Access log rotation | `logrotate/traefik` → /etc/logrotate.d | `sudo install -m 0644 logrotate/traefik /etc/logrotate.d/traefik` | `traefik.logrotate`: cmp with the repo → same | USR1 reopen behaviour |

## Authentik

All in Authentik's DB unless noted; one read-only `ak shell` pass (about 7 s).

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Pinned server tag | `.env` AUTHENTIK_TAG | edit, `docker compose up -d` (DB migrates: attended only) | `authentik.image-pin`: image → server:2026.x.y | one-way migration |
| Branding: brand title, logo, favicon, footer, flow titles | Brand + Tenant + 4 flows | README "Branding" | `authentik.brand`: → Holy Grail, logo/favicon from the branding store; `authentik.footer`: → holy-grail.ch link; `authentik.flow-titles`: → no "authentik" in the 4 titles | model renames |
| Branding mounts (logo, store at the same absolute path) | `docker-compose.yaml` server + worker | `docker compose up -d` | `authentik.brand-mounts`: logo file + store in both containers → ok ok | /web/icons path moves |
| Dashboard look: sections, captions, icons, hidden helpers, navy CSS | `scripts/dashboard-look.py`, icons in `data/media/public/apps` | `./scripts/fetch-app-icons.sh` then `ak shell < scripts/dashboard-look.py` | `authentik.dashboard-apps`: every APPS slug's group/description/icon → n/n; `authentik.dashboard-hidden`: → n/n; `authentik.dashboard-css`: brand CSS hash vs the script → match; `authentik.app-icons`: icon files → 10+ | the CSS uses undocumented selectors: also look at /if/user/#/library in a browser after every upgrade |
| Avatar source picker first | Tenant avatars | `Avatar-Picker/scripts/provision-authentik.py` | `authentik.avatar-source`: → attributes.avatar,initials | tenant field rename |
| Groups (admin split, media groups, cloud) | `scripts/provision-media-groups.py`, `provision-admin-account.py`, blueprints | `ak shell < scripts/provision-media-groups.py` | `authentik.groups`: 7 groups → 7/7; `authentik.admin-account`: jane-admin active → True | group model changes |
| App bindings per group | `scripts/provision-*-sso.py`, `provision-dt-sso.py` | rerun the provisioning (README "Re-running the provisioning") | `authentik.bind-homelab-admins`, `authentik.bind-streaming-admins`, `authentik.bind-streaming-requesters`, `authentik.bind-streaming-users`: bound apps → n/n | policy engine changes |
| Scope mappings: ABR groups, wg-easy email_verified, Audiobookshelf profile | `provision-books-sso.py`, `provision-admin-sso.py`, `blueprints/audiobookshelf-oidc.yaml` | provisioning / `ak apply_blueprint` | `authentik.abr-groups`: attached to books-login, emits abr_groups → True True; `authentik.wg-easy-email`: → True; `authentik.abs-oidc`: mapping + binding → True True | expression API changes |
| Login lifetime 1 day / 30 days, forward auth 24 h | stage default-authentication-login, all proxy providers; `access_token_validity` in every `provision-*.py` proxy helper | `scripts/session-ttl.sh apply`; new providers get 24 h from the provisioning | `authentik.session-ttl`: → days=1 days=29; `authentik.proxy-ttl`: every proxy provider at hours=24 → n/n | a new provider created outside the provisioning scripts starts at 1 h: rerun `session-ttl.sh apply` |
| Enrollment: streaming-users on sign-up, admin mail, invite warning | `blueprints/enrollment-*.yaml` | `docker cp` + `ak apply_blueprint` (README "Blueprints") | `authentik.enroll-group`: → streaming-users; `authentik.notify-new-user`: rule → True; `authentik.invite-warning`: binding → order=1 | blueprint schema |
| Embedded outpost serves every proxy provider | provisioning scripts | rerun the script of the app | `authentik.outpost-providers`: → missing=0 | outpost model |
| Avatar picker service account + role | `Avatar-Picker/scripts/provision-authentik.py` | rerun it | `authentik.avatar-picker-sa`: → True | RBAC changes |
| Canary user disabled between tests | `scripts/canary-*.sh` | `scripts/canary-disable.sh` | `authentik.canary-off`: is_active → False | none |
| Trusted proxy = Traefik only | `.env` AUTHENTIK_LISTEN__TRUSTED_PROXY_CIDRS | `docker compose up -d` | `authentik.trusted-proxy`: env → 127.0.0.0/8,::1/128,10.24.15.3/32 | setting rename |
| Email templates | `custom-templates/email/` mounted at /templates | `docker compose up -d` | `authentik.email-templates`: 3 templates in the container → ok | template context changes |
| App-list cache flush on group change | `scripts/app-cache-on-group-change.sh`, `systemd/authentik-app-cache.*` | README "Login lifetime" install line | `authentik.app-cache-timer`: → active | user_app_cache_key rename |
| Login page answers | stock flow + all of the above | | `authentik.login-page`: flow page → 200 | anything |

Full functional check (not read-only, it toggles the canary): `scripts/canary-verify.sh` → SSO_VERIFY_OK.

## Audiobook-Requests

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| ABR digest-pinned, root password + forwarded IPs entrypoint | `docker-compose.yaml` | `docker compose up -d` | `abr.image-pin`: → tag@sha256; `abr.forwarded-ips`: → 10.24.25.6 | upstream path changes (alembic, fastapi) |
| ABR settings: Prowlarr via the importer pass-through, auto-download, webhook, ABS via importer, OIDC | ABR DB | `sudo python3 scripts/abr-setup.py` | `abr.prowlarr-passthrough`: → importer URL [3030]; `abr.auto-download`: → True; `abr.webhook`: → enabled, importer /abr, onSuccessfulDownload; `abr.abs-via-importer`: → importer /abs, check on; `abr.oidc`: → oidc abr_groups https, no forced login; `abr.oidc-redirect`: /auth/login → sso authorize | settings API or migrations resetting values |
| books-proxy: Seerr + Library links injected, All-requests page (with sizes), Library page (viewer's own ABS view), Size column + sort on ABR's wishlist tables (`www/sizes.js`), request quota | `books-proxy/nginx.conf`, `books-proxy/www/` | `docker compose up -d books-proxy` | `books.links-inject`: login page carries links.js, links.js has the Seerr URL → 1; `books.all-requests`: page 200, data without ABR session 401; `books.quota`: importer /quota, auth_request lines → 204 2; `books.library`: page 200, data/cover/sizes without ABR session 401 ×3, sizes.js injected, links.js has Library | ABR renames endpoints (quota silently bypassed) or drops `</head>` |
| books-proxy: admits only Traefik (10.24.25.3) and 127.0.0.1, every other peer 403 (the `X-authentik-*` headers are trusted only because Traefik's forward auth overwrites them) | `books-proxy/nginx.conf` (`allow`/`deny` in `server`); direct checks run via `docker exec books-proxy curl` | `docker compose up -d --force-recreate books-proxy` | `books.peers-denied`: host data.json, host /, importer → 403 ×3, Traefik → health 200; `books.requests-unauth`: Traefik, no session → 302 sso | Traefik's address on traefik_mouse changes (books goes 403 for everyone) |
| books-proxy: requests bar (Seerr's shared bar: MAM usage, MAM unsatisfied torrents + rule risks via ABR-only `www/mam.js`, own quota, renewals, Library/Downloads disks), only after Holy Grail + ABR login; `bar.{js,css}` vendored unchanged from beefy (canonical), never edited here | `books-proxy/www/bar/`, `abr-bar/indexer-bar-schema.md`, `books-proxy/nginx.conf` (`/_hg/bar/*`, `auth_request` → ABR `/api/users/me`, sub_filter with `data-ib-*`), `books-proxy/www/mam.js`, `scripts/abr_bar_usage.py` (qBittorrent read-only, `mouse/secrets/qbit_pass` as credential) + `systemd/abr-bar-usage.timer` → `/var/lib/abr-bar` (mounted ro), `abr-bar/limits.toml`, importer `/my-quota`, `scripts/sync-bar.sh` | `sudo install -m 0644 systemd/abr-bar-usage.* /etc/systemd/system/ && sudo systemctl enable --now abr-bar-usage.timer`; `bash scripts/sync-bar.sh`; `docker compose up -d books-proxy` | `books.bar-inject`: → bar.css bar.js 200; `books.bar-data`: → fresh ok active; `books.bar-unauth`: no session, LAN + Cloudflare → 302 sso ×4; `books.bar-needs-abr-session`: → 401 401; `books.mam-inject`: → _hg/mam.js 200; `books.mam-unsatisfied`: → ok n/limit; `books.bar-shared`: hash = beefy HEAD → same (or skipped, beefy asleep); `importer.my-quota`: → 403 400 | ABR drops `</head>`, renames `/login` or `/api/users/me`; Prowlarr history API; qBittorrent API (`torrents/info` fields, login), password change in `mouse/secrets/qbit_pass` (credential re-read each run); Seerr bar changed but not synced |
| books-proxy: download buttons that skip a request (`/wishlist/hx-auto-download/`, `/api/requests/<id>/` auto-download, download, refresh) admin only | `books-proxy/nginx.conf` (map on `X-authentik-groups` = `streaming-admins`) | `docker compose up -d books-proxy` | `books.admin-only-downloads`: requester POST → 403 403 | ABR route renames |
| Importer: quota ledger (deleted requests keep counting), `/quota` + `/all-requests` + `/library` + `/library-cover/` + `/sizes` only from books-proxy, `/prowlarr/torrent`, `POST /abr`, `POST /prowlarr/*` only from ABR, POST bodies over 1 MB 413, ABS down on `/abs` 502; library + sizes (also on All requests) read ABS with its key (GET: libraries, items, users) and filter by the viewer's ABS permissions, viewer = OIDC-linked ABS account only (`hasOpenIDLink`), never root | `importer/importer.py`, `importer/library.py`, `data/quota.json` | `docker compose up -d importer` | `importer.callers`: host → the six paths 403 ×6 and books-proxy → /quota 204; `importer.library`: unknown viewer → True 0, sizes is a JSON object; `importer.post-callers`: host POST /abr, /prowlarr → 403 403 | ABR request API fields, ABS items/users API fields or permission model or `hasOpenIDLink` field, container addresses |
| Importer: ranking pass-through, read-only ABS gate | `importer/` (mounted ro) | `docker compose up -d importer` | `importer.health`: → ok; `importer.abs-readonly-gate`: POST scan → 404; `importer.ranking-tests`: unit tests → OK | ABR's Prowlarr call shape |

## audiobookshelf

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| OIDC only (local login off), Holy Grail button, auto-register, match by email, groups claim | ABS DB server-settings (UI Settings → Authentication) | ABS UI | `abs.oidc-only`: public /status → [openid] Login with Holy Grail; `abs.oidc-settings`: → True email groups issuer | a migration re-enabling local login |
| Service users: abr read-only, audiobook-importer update only | ABS DB users (UI Users) | ABS UI, keys per `Audiobook-Requests/README.md` | `abs.user-abr`: → user, active, all four perms False; `abs.user-importer`: → admin, active, only update True | permission model changes |
| Root locked (random password + token), one root | ABS DB | ABS UI | `abs.root-single`: root users → 1 | none |
| One library per language | ABS DB | ABS UI | `abs.libraries`: → 3+ | none |
| Service user `floppy-sync` (admin, random password) + its one API key `floppy-sync`, read by beefy's `floppy-abs-push` to sync every ABS user with a same-named Floppy user (HomeLab-BeefyServer `Floppy/README.md` "Audiobookshelf push"); admin because only `GET /api/users/:id` returns other users' progress; key root-only on beefy, used GET-only | ABS DB users + apiKeys (UI Users, Settings → API Keys) | ABS UI, then beefy `sudo Floppy/scripts/abs-push.py store-key` | `abs.key-floppy-sync`: → admin True floppy-sync | user or key renamed or demoted (beefy refuses a key that is not the admin `floppy-sync`) |

## mouse (VPN downloaders)

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Samba on `lo`+`eth0` only (smbd/nmbd `interfaces`, wsdd2 `-i eth0`, avahi `allow-interfaces`), encryption required | `mouse/docker-compose.yaml` samba env (`SAMBA_GLOBAL_CONFIG_*`, `WSDD2_PARAMETERS`, `AVAHI_INTERFACES`) | `docker compose up -d --no-deps samba` | `mouse.samba-lan-only`: → none Yes required | the image renaming its env options (`:latest`) |
| Prowlarr MAM rules, seed forever | Prowlarr DB + qBittorrent prefs | `sudo python3 scripts/prowlarr-setup.py` | `mouse.prowlarr-setup`: prowlarr-setup.py --check → OK MAM rules, gate and seed-forever hold | indexer field renames |
| prowlarr-gate (only Traefik gets the UI), Prowlarr digest pin | `prowlarr-gate/nginx.conf`, `docker-compose.yaml` | `docker compose up -d prowlarr-gate` | `mouse.prowlarr-gate`: UI from the host → 403; `mouse.prowlarr-pin`: → 2.7.0.5723-ls166@sha256 | host config resetting bindAddress |
| gluetun lo guard: only prowlarr-gate (uid 65057) and Prowlarr (65054) reach 127.0.0.1:9696, qBit/SAB/Mousehole refused (S-05) | `gluetun/post-rules.txt` mounted at `/iptables/post-rules.txt` | `docker compose up -d gluetun` (restarts the netns stack) | `mouse.prowlarr-lo-guard`: qBittorrent → 9696 = 000, gate → 9696 ok | gluetun post-rules path/format, container uids, iptables owner match |
| qBittorrent stays on 5.2.x (MAM client rules) | `docker-compose.yaml` | keep the tag | `mouse.qbit-5.2-pin`: qbittorrent-nox --version → v5.2. | a tag bump to 5.3+ |
| qBittorrent auth bypass only for Traefik, bound to tun0, category abr | qBittorrent.conf, categories.json under /mnt/seagate-red/qbittorrent/config | WebUI options / prowlarr-setup.py | `mouse.qbit-auth-bypass`: → 10.24.25.3/32, enabled; `mouse.qbit-bypass-scope`: importer asks → 403; `mouse.qbit-vpn-bind`: → tun0 tun0; `mouse.qbit-category-abr`: → /downloads/complete/abr -2 -2 -2 | config migration |
| Forwarded port: TORRENTING_PORT + port_updater | `docker-compose.yaml`, `port-updater/` | `docker compose up -d port-updater` | `mouse.torrenting-port`: env set; `mouse.port-updater-sync`: log → Port OK; `mouse.port-updater-login`: anon → 401 | linuxserver init changes |
| gluetun pinned, ASN-locked server, port forwarding, control-server auth | `docker-compose.yaml`, `secrets/gluetun/auth/config.toml` | `docker compose up -d gluetun` | `mouse.gluetun-pin`: → v3.41.3; `mouse.gluetun-server`: → node-ch-07, forwarding on; `mouse.gluetun-control-auth`: anon → 401 401; `mouse.vpn-egress`: qBittorrent IP ≠ home IP → vpn | auth schema change |
| SABnzbd local ranges + host whitelist | sabnzbd.ini [misc] (edit only while stopped) | edit with the container stopped | `mouse.sab-whitelist`: → the four ranges, host listed True; `mouse.sab-localhost`: :8090 → 200 | sabnzbd:latest migrating the ini |
| Mousehole keeps the MAM session | `docker-compose.yaml` | `docker compose up -d mousehole` | `mouse.mousehole-mam`: /health → ok | state path changes (0.5) |

## antivirus

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Own scripts + freshclam config baked into clamav-local | `clamav/` (Dockerfile COPY) | `docker compose up -d --build --pull clamav virustotal` | `av.scripts-in-image`: sha256 of the three scripts in the image vs repo → same same same; `av.freshclam-conf`: → same; `av.freshclam-running`: → 1+ | alpine base changes (busybox flags): run tests/test_scan.sh in the image |
| Nightly new-files scan, weekly host scan (nightly 22:30 timer, window 22:00-06:00 + Sunday, resumable) | `systemd/clamav-*`, `install.sh` | `./install.sh` | `av.timers`: → active active, units same as repo; `av.services`: units same as repo; `av.nightly-scan`: last run → under 2 days | none |
| `new`/`all` in `clamav` skip Prowlarr's config dir (`SCAN_EXCLUDE_DIRS=/scan/seagate-red/prowlarr`, unreadable for 65039 by design) | `docker-compose.yaml` clamav env, `clamav/scan.sh` `list_find` | `docker compose up -d --build clamav` | `av.nightly-scan`: last run → under 2 days | none |
| Host scan without network, resumable, low priority, exclude list | `docker-compose.yaml` profile hostscan | `docker compose up -d --build clamav` (image) | `av.hostscan-no-network`: network_mode → none; `av.hostscan-resume`: SCAN_RESUME=1 and cpu_shares 2 in the config | none |

## Home-Assistant

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| SSO only: hass-oidc-auth 1.2.1 vendored, password provider removed | `config/custom_components/auth_oidc/`, `config/configuration.yaml` | README "Installing / updating the component" | `ha.sso-only`: /auth/providers → auth_oidc; `ha.oidc-vendored`: manifest → 1.2.1, tree clean; `ha.oidc-redirect`: welcome → sso authorize with the ha callback | HA core change stops the component: zero login methods (README shell recovery) |
| Proxy trust | `config/.storage/http` | UI Network, or edit with HA stopped | `ha.http-trust`: → True [172.24.0.0/16]; `ha.via-traefik`: → 200 | storage migration dropping keys (400 on every request) |
| Zigbee dongle by-id | `docker-compose.yaml` | `docker compose up -d` | `ha.zigbee-device`: /dev/ttyUSB0 → ok | none |
| Person pictures = Avatar-Picker picks (websocket `person/update`, token `Avatar-Picker/secrets/ha_token`) | HA `.storage/person` | `python3 Avatar-Picker/scripts/avatar-sync.py --reconcile` | `ha.person-pictures`: pictures vs picks → ok n/n | websocket person API change |

## grafana (monitoring stack)

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Grafana SSO only (generic OAuth, form + basic off) | `docker-compose.yaml` GF_AUTH_* | `docker compose up -d grafana` | `grafana.oauth-login`: /login → sso authorize; `grafana.login-form-off`: POST /login → notConfigured; `grafana.basic-auth-off`: → 401 | GF env renames |
| Provisioned dashboards | `provisioning/` | restart grafana | `grafana.dashboards`: every uid in provisioning/dashboards in the DB → ok | unified-storage schema |
| Prometheus rules, retention, scrape jobs | `prometheus/` | `docker kill -s HUP prometheus` | `prom.rule-files`: loaded files = repo files, rules ok → n n [] 0; `prom.retention`: → 400d 60GiB; `prom.scrape-jobs`: jobs = pools, none down → n n 0 | flag or rule syntax changes |
| Alertmanager routing, quiet hours, Telegram template; intrusion alerts (`SshLoginOutsideLan` unknown source, `SshLoginUnexpectedUser`, `SecurityFileChanged`, `BeefyBackupSnapshotInFuture`) → `telegram-and-email`, never muted | `alertmanager/alertmanager.yml` (gitignored), `alertmanager/templates/` | edit in place, amtool check-config, HUP | `am.config`: quiet-hours, Europe/Zurich, templates → True True True telegram.tmpl; `am.routes`: warning, critical, digest, DailyDigest → telegram critical null telegram-digest; `am.routing-tests`: test_routing.py → OK ; `am.intrusion-route`: SshLoginOutsideLan from an unknown source → telegram-and-email | config schema |
| Blackbox modules (LAN + WAN) | `blackbox/blackbox.yml` | restart | `blackbox.modules`: module count both exporters → n n | config schema |
| Telegraf docker input → InfluxDB, InfluxDB 2.x pin | `telegraf/telegraf.conf`, `docker-compose.yaml` | restart | `telegraf.writes`: output errors in 5 min → 0; `influxdb.v2-pin`: /health → v2.9.1 pass | influxdb:latest is v3 |
| node-exporter textfile collector (security, backups, scans) | `docker-compose.yaml` | restart | `node.textfile-collector`: scrape error, files → 0 n | flag rename |
| Host jobs: container exporter, usage collector, status exporter (certs, domains, subscriptions, indexers), SMART exporter | `container-exporter/systemd/`, `usage-collector/systemd/`, `status-exporter/systemd/`, `smart-exporter/systemd/` (+ `smartmontools` apt package) | README install lines | `grafana.host-timers`: → active ×5; `grafana.container-exporter`: last success → under 3 min; `grafana.status-exporter`: certs run under 2 days, hosts with a handshake → yes n; `grafana.smart-exporter`: fastpi run under 2 h, unreadable disks → yes 0 | smartctl JSON keys (smartmontools upgrade) |

## Portainer

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| OAuth only, port on 127.0.0.1 | Portainer DB, `docker-compose.yaml` | Portainer UI Authentication | `portainer.oauth-only`: → AuthenticationMethod 3; `portainer.oauth-sso`: login URI → sso authorize, redirect portainer; `portainer.localhost-only`: LAN :9443 → 000 | DB migration resetting OAuth |
| Read-only socket proxy | `docker-compose.yaml` | `docker compose up -d socket-proxy` | `portainer.proxy-readonly`: → EXEC=0 POST=0 | env renames |
| Socket proxy + socat pinned by digest (A-30) | `.env` `SOCKET_PROXY_TAG`, `docker-compose.yaml` | new digest into `.env`, `.env.example`, compose; `docker compose up -d` | `portainer.image-pin`: → pinned 2/2, running = pin 2/2 | none (a re-pushed tag no longer moves the image) |

## Docker-Socket-Proxy

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Read-only proxy allow-list | `docker-compose.yaml` | `docker compose up -d` | `dsp.ro-env`: → CONTAINERS EVENTS IMAGES INFO PING VERSION; `dsp.ro-denies-post`: GET version, POST restart → 200 403 | env renames |
| haproxy overlays for autoheal and port_updater | `autoheal-haproxy.cfg`, `portupdater-haproxy.cfg` | `docker compose up -d` | `dsp.haproxy-overlays`: mounted cfg vs repo → match match; `dsp.autoheal-denies`: /info → 403; `dsp.portupdater-scope`: gluetun / traefik inspect → 200 403 | image moving its haproxy path (overlay ignored) |
| All proxies + socat pinned by digest (A-30) | `.env` `SOCKET_PROXY_TAG`, `docker-compose.yaml` | new digest into `.env`, `.env.example`, compose; `docker compose up -d` | `dsp.image-pin`: → pinned 4/4, running = pin 4/4 | none (auto-update sees the pin as current; Cup still shows new tags) |

## WireguardVPN

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| OIDC only, password login off, secret via entrypoint | `docker-compose.yaml` | `docker compose up -d` | `wg.oidc-env`: → the four env values; `wg.password-off`: auth methods → passwordDisabled; `wg.password-post`: → 403; `wg.oidc-sso`: → sso authorize with the wg-easy callback; `wg.secret-entrypoint`: entrypoint reads oidc_client_secret | env renames, docker-entrypoint.sh moves |
| Hooks: iptables-nft + DNAT of web traffic to Traefik | wg-easy DB hooks_table | Admin → Hooks | `wg.dnat-hook`: PREROUTING DNAT → 1; `wg.hooks-nft`: post_up/post_down only iptables-nft → (5, 0, True) twice; `wg.listening`: → 51820 | iptables backend switch (2026-10-25 restart loop) |

## LanguageTool (compose dir LanguageTool/Raspi, checks in Raspi.sh)

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Local image, own entrypoint, logback, shared rules + spelling | `Raspi/Dockerfile`, `shared/`, `Raspi/config/` | `docker compose -f Raspi/docker-compose.yaml up -d --build` | `lt.local-image`: → languagetool-local:6.8; `lt.entrypoint-logback`: → /LanguageTool/logback.xml; `lt.rules-spelling`: Raspi/scripts/test.sh → PASS n FAIL 0 | upstream start.sh changes |

Token routers: `traefik.lt-token-routers` (Traefik).

## CrowdSec

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Collections, Traefik log acquisition | `docker-compose.yaml` COLLECTIONS, `config/acquis.yaml` | `docker compose up -d` | `cs.collections`: traefik, http-cve, base-http-scenarios → ok; `cs.acquis-traefik`: acquisition metrics → 1+ | hub renames |
| Home IP allowlist (LAPI DB) | README "Home IP allowlist" | cscli allowlists add home | `cs.allowlist-home`: → is allowlisted | DB migration |
| LAPI + bouncer, exporter + autoupdate timers | `systemd/` | `install.sh` | `cs.lapi`: → successfully; `cs.bouncer-pull`: → under 10 min; `cs.units`: → active active | none |

## cloudflared

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Pinned tag, no autoupdate, metrics, token file | `docker-compose.yaml` | `docker compose up -d` | `cf.pin`: → cloudflared:YYYY.M.P; `cf.no-autoupdate-metrics`: → command flags; `cf.tunnel-connections`: → 1+ | flag changes |
| Address in the host-guard SSH range | `docker-compose.yaml` network | `docker compose up -d` | `cf.host-guard-range`: → 172.20.; `cf.public-path`: home through Cloudflare → 200 | network recreated |

## adguard

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Only the authentik-proxy user, lockout 5 / 15 min | `conf/AdGuardHome.yaml` (root-owned) | edit with the container stopped | `adg.users`: → [authentik-proxy], 5, 15; `adg.anon-refused`: → 401; `adg.ui-sso`: → sso | schema_version bump rewriting the YAML |
| Local zone *.holy-grail.ch → fastpi | same file, rewrites | AdGuard UI | `adg.local-zone`: sso → 192.168.1.2; `adg.resolves`: example.com → an IP | same |

## Cup

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| No socket, agents per host, 172.24.0.1 bind, forward auth | `cup.json`, `cup-agent.json`, `docker-compose.yaml` | `docker compose up -d` | `cup.config`: → socket none, servers beefy, fastpi; `cup.api-servers`: API lists beefy and fastpi; `cup.bind-172`: LAN :8000 → 000; `cup.forward-auth`: → sso | config schema version |
| Rollback tags excluded: `images.exclude` `rollback.invalid/` + `registries.rollback.invalid.ignore` (UPDATE-RUNBOOK.md "Rollback tags") | `cup.json`, `cup-agent.json` | `docker restart cup-agent-fastpi Cup` | `cup.exclude-rollback`: → both files; `cup.rollback-tags-last`: in-use image with a rollback tag first → 0; `cup.no-crash-loop`: → stable over 12 s | exclude semantics (3.6: prefix match on the reference, only the first tag is read) |

## Avatar-Picker

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Local avatar pack, favicon, version in the image | `app/img-local/` (gitignored), `app/static/`, `Dockerfile` | `docker compose up -d --build` | `avatar.local-pack`: every local gallery file in the image → n local, 0 missing; `avatar.favicon`: → 200 200; `avatar.version`: image vs repo → same | a rebuild without the pack |
| Gallery thumbnails (160/320 px WebP, content-hashed URLs, `private, max-age=31536000, immutable`), PNG fallback, gzip for page + state | `scripts/build_thumbs.py` (Dockerfile stage `thumbs`, Pillow pinned by hash), `app/server.py` `/thumb/`, `app/static/index.html` | `docker compose up -d --build` | `avatar.thumbs`: → n/n thumbs, private immutable, gzip | a Pillow bump without a new hash; Dockerfile without the `thumbs` stage |
| State via Authentik, header secret from Traefik | `secrets/`, `Traefik/traefik/dynamic/avatar-picker-secret.yml` | `scripts/rotate-secrets.sh` | `avatar.state`: → 200 groups avatars lotr; `avatar.secret-required`: without header → 403 | Authentik API changes (503) |
| Pick queue + host sync to Jellyfin, Seerr (wakes beefy for a pending pick), Home Assistant (Nextcloud prepared, inactive); retry timer only while pending | `data/queue.json`, `scripts/avatar-sync.py`, `systemd/avatar-sync*`, `secrets/ha_token` | README install line | `avatar.queue`: → ok; `avatar.sync-units`: path + boot run → active enabled success; `avatar.retry-timer`: → in sync inactive, or pending n active; `avatar.ha-pictures`: HA person pictures vs picks → ok n/n | HA websocket person API, Jellyfin /UserImage, Seerr user table |
| API token expires after 365 days, rotated 45 days before (new token, verify as the container, delete old; old token back on failure), expiry metric | `scripts/rotate-secrets.sh token-auto`, `systemd/avatar-token-rotate.*`, `authentik_tokens.prom`, `grafana/prometheus/rules/authentik-tokens.yml` | README install line | `avatar.token-rotate`: timer active, > 30 days left → active ok | Authentik Token model fields |
| Image routes: LAN all, outside picked only (rest needs a login session) | `Traefik/traefik/dynamic/avatar-picker.yml` (`X-Avatar-Access` header), `app/server.py` | file reload, `docker compose up -d --build` | `avatar.img-routes`: public picked / public unpicked / LAN → 200 403 200 | ClientIP rule changes, Authentik `users/me` semantics |

## Beefy-Waker

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Waker app (listen backlog 64 via `Server.request_queue_size`) | `app/` | `docker compose up -d --build` | `waker.status`: → up; `waker.version`: page vs app/VERSION → same; `waker.ssh-user`: passwd name of the container uid → waker (the `/history` ssh needs it) | base image; a uid change in compose without the `Dockerfile` |
| Stream auth `/stream-auth` for Traefik (token from headers or `api_key`/`ApiKey`, checked with Jellyfin `/System/Info`, 60 s cache) | `app/waker.py` | `docker compose restart waker` | `waker.stream-auth`: no token / malformed token → 401 401 | Jellyfin auth header format |
| Night downloads poll/wake (both `User=pi`), maintenance wake, idle pull (also copies beefy storage + mover metrics) | `night-downloads-wake/`, `maintenance-wake/`, `Server/4-Security-Monitoring/beefy-idle-pull.*` | copy units to /etc/systemd/system, enable | `waker.timers`: → four active; `waker.units-installed`: → same same same; `waker.night-wake-user`: wake unit runs as pi, not root → pi | none |
| ssh wake hooks (send `-H X-Wake:1`) | ~/.ssh/config Match exec | by hand | `waker.ssh-hooks`: → 2 | none |
| Wake CSRF guard: `POST /wake`, `/jf/wake` need `X-Wake: 1`, browser `Origin` must be this host (D-11); python base pinned by digest (A-30) | `app/waker.py`, `Dockerfile` | `docker compose up -d --build` | `waker.wake-csrf`: no header / foreign origin → 403 403 | none |
| Night downloads wake ignores a cache older than 24 h (A-31) | `night-downloads-wake/beefy-night-downloads` | runs from the repo | `test_beefy_night_downloads.py` | none |

## Tower-Waker

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Wake CSRF guard: `POST /wake`, `/nc/wake` need `X-Wake: 1`, browser `Origin` must be this host (D-11); python base pinned by digest (A-30) | `app/waker.py`, `Dockerfile` | `docker compose up -d --build` | `tower-waker.status`: → up key; `tower-waker.wake-csrf`: no header / foreign origin → 403 403 (never wakes) | none |

## Claude-Mockups

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Caddyfile, answer assets, answer inbox | `Caddyfile`, `assets/`, `inbox/server.js` | `docker compose up -d --force-recreate` | `mockups.caddyfile`: caddy validate → Valid configuration; `mockups.assets`: → ok; `mockups.answer-inbox`: → ok; `mockups.forward-auth`: → sso | caddy directive changes (auto-updated) |

## Wiki

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Static site served read-only from www/ (built by build.sh), 404 page | `Caddyfile`, `www/` | `docker compose up -d --force-recreate` | `wiki.caddyfile`: caddy validate → Valid configuration; `wiki.site`: index → 200 + bytes; `wiki.not-found`: unknown path → 404 | caddy directive changes (auto-updated) |

## Server-Specs

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Static specs page served read-only from www/ | `Caddyfile`, `www/` | `docker compose up -d --force-recreate` | `specs.caddyfile`: caddy validate → Valid configuration; `specs.page`: index → 200 + bytes | caddy directive changes (auto-updated) |

## Host (fastpi, no compose project)

| Customization | Where | Reapply | Verify | Update can break |
|---|---|---|---|---|
| Security monitoring timers | `Server/4-Security-Monitoring/` | its `install.sh` | `host.security-timers`: eight timers → active; `host.security-units-installed`: units differing from the repo → 0; `host.security-scan-fresh`: stale alerts → none | none |
| Nightly auto-update + image cleanup | `_global/systemd/` | its install line | `host.auto-update-timer`: → active active | none |
| Corrupt-download alert path: beefy's `download-integrity.prom` + hits file pulled into `download_integrity_beefy.prom` and `download_integrity_hit_info`, rules `DownloadCorrupt` / `DownloadIntegrityErrors` / `DownloadIntegrityMetricsMissing`, digest line | `Server/4-Security-Monitoring/security_scan.py` (`AV_PATHS["beefy"]`), `Docker/grafana/prometheus/rules/antivirus.yml`, `weekly-digest.yml` | `Docker/_global/install-root-scripts.sh`; `docker kill -s HUP prometheus` | `host.root-scripts`: → 0; `prom.rule-files`: → n n [] 0; `promtool test rules tests/antivirus_test.yml` | a rename of beefy's metrics or files (`download-integrity.py`) |
| Shared node-exporter textfile dir `pi:65046 2775` (gid 65046 = clamav-scan and other non-pi writers) | `/var/lib/node-exporter/textfile`, the four installers (`antivirus`, `CrowdSec`, `_global/install-image-cleanup.sh`, `4-Security-Monitoring`) | `sudo install -d -o pi -g 65046 -m 2775 /var/lib/node-exporter/textfile` | `host.textfile-perms`: → pi:65046 2775 | an installer that resets it (`_global/scripts/test_textfile_dir.sh` guards them) |
| Root units run root-owned copies (`container_exporter.py`, `smart_exporter.py`, `security_scan.py` for `security-access`), never pi-writable code; units sandboxed (exposure 3.7) | `/usr/local/libexec/fastpi`, `_global/install-root-scripts.sh` | `Docker/_global/install-root-scripts.sh` (after every edit of one of the scripts) | `host.root-scripts`: copies differing or not root:root 0644 → 0; `_global/scripts/test_root_units.sh` | none |
| Host firewall guard persisted | /etc/iptables/rules.v4 | `_global/scripts/iptables-persist.sh` | `host.host-guard-persisted`: → 1 | iptables-persistent changes |
| Backup: rest-server 0.14.0 for beefy's repo (append-only, private repos, TLS, `IPAddressAllow` beefy only, 192.168.1.2:8009), beefy-repo-maint 05:07 (user `beefy-backup`, password via `LoadCredential=`, metric published by root `ExecStopPost`, refuses forget on snapshots dated > 1 h ahead, `--keep-within 30d`; rest-server `InaccessiblePaths=/run/credentials`), fastpi-backup 04:06, restore test monthly (beefy repo `--no-lock`) | `Server/5-Backup/` | its `install.sh` (`setup-beefy-repo.sh` once) | `host.backup-rest`: → active append-only beefy-only; `host.backup-timers`: → active active active; `host.beefy-repo-maint`: → beefy-backup 0 (user, repo files not owned by it); `host.backup-scripts`: /usr/local/sbin copies differing → 0; `host.backup-rest-nocreds`: → -/run/credentials | rest-server flag rename; a systemd change to `IPAddressAllow` or `LoadCredential` |
