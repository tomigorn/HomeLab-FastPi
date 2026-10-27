# Admin split: `tomigorn` (everyday) + `tomigorn-admin` (admin)

Least privilege: the everyday account keeps watching, listening, requesting; every admin right moves to a separate account with its own password + MFA. `akadmin` stays the Authentik break-glass superuser, untouched.

| Phase | What | State |
|---|---|---|
| 1 | inventory, this plan, create `tomigorn-admin` (`scripts/provision-admin-account.py`), owner sets password + MFA via a one-time recovery link | done 2026-10-27 |
| 2a | add `tomigorn-admin` to the admin groups, set up per-app admin users, verify each app as `tomigorn-admin` | groups added 2026-10-27 (`provision-media-groups.py` `MEMBERS`), app logins open |
| 2b | only after 2a verified everywhere: remove `tomigorn` from the admin groups, demote/delete old admin users in the apps | done 2026-10-27 except DT user delete and Floppy link (by hand, see Phase 2b state) |
| 3 | Nextcloud (`cloud-admins`, tower) | deferred until tower's RAM test ends |

## The two accounts

| | `tomigorn` | `tomigorn-admin` |
|---|---|---|
| Groups after phase 2 | `streaming-users`, `streaming-requesters`, `cloud-users` | `homelab-admins`, `streaming-admins` (+ `streaming-users` / `streaming-requesters` only where an app's gate needs it, see table), later `cloud-admins` |
| Email | everyday mailbox | same mailbox as plus-address `+admin` (unique, so email matching never mixes them) |
| Keeps | Jellyfin watch history, ABS progress, Seerr/ABR requests, Floppy tracker, HA person + device trackers, avatar | nothing personal |

## Phase 1 facts (checked 2026-10-27)

- Login flow `default-authentication-flow`: identification → password → `default-authentication-mfa-validation` (`not_configured_action=configure`, configuration stage `default-authenticator-totp-setup`) → login. The MFA binding policy skips only for passwordless WebAuthn. A user without MFA is forced to enrol TOTP at the first normal login.
- Recovery link (`ak create_recovery_key <minutes> <user>`): single use, logs the user in directly (no MFA, brand safe mode) and opens the user interface. Password: User settings → Change password (`default-password-change`). MFA: User settings → MFA devices, or forced at the next normal login.
- The brand recovery flow ("Forgot password?") needs existing TOTP, so it cannot onboard a user without MFA; the recovery key is the supported path.
- Every OIDC provider uses `sub_mode=hashed_user_id` (Nextcloud: `user_uuid`): a new Authentik user is a new identity in every OIDC app.

## Per app

Gate = Authentik application binding (who may open it at all). Phase 2a step = with `tomigorn` still admin, so nothing locks out. Phase 2b = remove `tomigorn` from the group and clean up.

| App | Admin mechanism | (a) `tomigorn-admin` added | (b) `tomigorn` removed | Phase-2 steps | Verify | Rollback / break-glass |
|---|---|---|---|---|---|---|
| Traefik dashboard, Cup, Claude-Mockups, VPN status beefy + mouse, AdGuard | forward auth, gate `homelab-admins` only (AdGuard/mouse: Basic injected from group attributes, group-wide) | opens at once (app cache timer clears the dashboard list within 1 min) | denied by the gate at the next forward-auth session refresh (≤ 24 h; end sessions to force) | 2a: add to `homelab-admins`. 2b: remove `tomigorn`, Directory → Users → tomigorn → Sessions → delete | each URL as `tomigorn-admin` opens; as `tomigorn` shows "access denied" | re-add `tomigorn` to the group; Traefik: drop a router file; AdGuard: shell user (README) |
| Specs (`server-specs`), Wiki, Avatar picker | no binding: every logged-in user | works | still works (by design) | none | – | – |
| Grafana | OIDC, `ALLOWED_GROUPS=homelab-admins`, `GrafanaAdmin` from groups at every login; users matched by email/login | new Grafana user `tomigorn-admin`, GrafanaAdmin on first login | `tomigorn` refused; old Grafana user stays orphaned | 2a: login once. 2b: delete Grafana user `tomigorn` (dashboards are org-owned, nothing lost; only stars/prefs) | Admin → Users shows `tomigorn-admin` as Grafana Admin | re-add group; shell: `GF_AUTH_DISABLE_LOGIN_FORM=false` + local admin (README) |
| Portainer | CE OAuth, auto-provisioning OFF: admin = pre-created Portainer user `tomigorn` | Portainer user `tomigorn-admin` (id 3, Administrator, no password) created 2026-10-27 via API as initial admin | Authentik gate refuses `tomigorn` | 2a: as `tomigorn` in Portainer (or initial admin over `ssh -L 9443`): Users → add `tomigorn-admin`, role Administrator; log in via Holy Grail as it. 2b: delete Portainer user `tomigorn` | `tomigorn-admin` sees both environments | initial admin via `ssh -L 9443:127.0.0.1:9443 fastpi` → `/#!/internal-auth`; `helper-reset-password` |
| wg-easy | OIDC, auto-register off; one user `admin` (id 1) linked by `oauth_id` to `tomigorn` | refused (no linked user) | gate refuses `tomigorn`; nobody can log in until re-linked | 2a+2b together (one user only): back up `wg-easy-v15/wg-easy.db`, stop container (drops VPN tunnels ~3 s, attended), set user 1 `email` = admin plus-address, `oauth_id`/`oauth_provider` = NULL, start; log in as `tomigorn-admin` → links by email | wg-easy opens as `tomigorn-admin`; `tomigorn` refused | restore the db backup; `DISABLE_PASSWORD_AUTH=false` + `cli db:admin:reset` (compose comments) |
| Home Assistant | `hass-oidc-auth`, roles admin+user = `homelab-admins`, set at FIRST login only; owner flag = OIDC user "Tomigorn" | first login creates a new HA admin user + person | Authentik gate refuses new logins, but HA refresh tokens (Companion app!) of `tomigorn` keep working until revoked | 2a: login once as `tomigorn-admin`. Owner transfer: HA stopped, back up `config/.storage/auth`, move `is_owner` to the new user. 2b: decide whether `tomigorn` keeps HA as non-admin (needs a non-admin group mapped to `roles.user`) or loses it (revoke refresh tokens, deactivate) | new user shows Owner + Administrator | restore `.storage/auth`; shell recovery: re-add `homeassistant` auth provider (HA README) |
| Dependency-Track (beefy) | forward auth + OIDC `dt-login`, gate `homelab-admins`; user = `preferred_username`, teams synced from `groups` at every login (`homelab-admins` → Administrators) | new DT user `tomigorn-admin` in Administrators | gate refuses `tomigorn`; old DT user stays | 2a: login once. 2b: delete DT user `tomigorn` | `tomigorn-admin` in team Administrators | local `admin` (beefy `secrets/dt_admin_password`) |
| Radarr, Sonarr, Prowlarr, Bazarr, SABnzbd, qBittorrent (beefy) + qBit/SAB/Prowlarr audiobooks (fastpi) | forward auth only, gate `streaming-admins`; apps have no own users | opens | refused | 2a: add to `streaming-admins`. 2b: remove `tomigorn` | each opens as `tomigorn-admin` | re-add group; LAN `ssh -L` to the app port |
| Jellyfin (beefy) | OIDC plugin, sign-in gate `streaming-users` (Authentik binding), admin = direct `streaming-admins` membership, set/removed at EVERY sign-in; user matched by username | needs `streaming-users` too to pass the gate; then a new Jellyfin user `tomigorn-admin`, administrator, empty history | `tomigorn` loses administrator at next sign-in; history, favourites, Quick Connect stay | 2a: add to `streaming-users` + `streaming-admins`, sign in once (wake beefy), restrict its library access if wanted. 2b: remove `tomigorn` from `streaming-admins`, sign in once as `tomigorn` (demotion applies on sign-in) | Dashboard reachable as `tomigorn-admin`, not as `tomigorn` | re-add group + sign in; sqlite recovery (Jellyfin README) |
| Audiobookshelf | OIDC, auto-register on, match existing by email, `groups` claim → `admin`/`user` at every login; gate `streaming-users` OR policy `audiobookshelf-access` (admins pass alone); local `root` user exists, password login off | new ABS user `tomigorn-admin`, type admin | `tomigorn` becomes type `user` only at its next OIDC callback (an open ABS session never re-checks: demote via API), progress/bookmarks stay; bonus: Floppy may then link `tomigorn` (it refuses ABS admins) | 2a: add to `streaming-admins` (no `streaming-users` needed), log in once. 2b: remove `tomigorn`, log in once as `tomigorn`, check its library access | `tomigorn-admin` sees Settings; `tomigorn` sees no Settings, progress intact | re-add group; enable local auth in DB + `root` |
| AudioBookRequest | OIDC, gate `streaming-requesters`; `abr_groups` claim: `streaming-admins` → admin | needs `streaming-requesters` to pass the gate; new ABR user `tomigorn-admin`, admin | `tomigorn` becomes `trusted` (if ABR re-reads the role at login: verify) | 2a: add to `streaming-requesters`, log in once. 2b: remove `tomigorn`, log in once, check role | ABR Settings as `tomigorn-admin` only | `ABR_FORCE_LOGIN_TYPE=forms` + `abr-root` (ABR README) |
| Seerr (beefy) | OIDC `requests-login`, gate `streaming-requesters`; owner = user id 1 = `tomigorn` (Jellyfin-type, linked); id 1 always has every permission, no ownership transfer | needs `streaming-requesters`; first press creates a new Seerr user with default permissions (new user login on) | nothing: Seerr permissions are local; id 1 stays owner | owner 2026-10-27: B, see 2b runbook (`admin-split-seerr-transfer.sql`) | as chosen | Seerr settings backup + `linked_accounts` sqlite (Seerr README) |
| Floppy / Tracker (beefy) | OIDC, gate `streaming-users`; no admin user at all | nothing to do | nothing | none | – | – |
| Authentik itself | `tomigorn` is not superuser; `akadmin` (`authentik Admins`) = superuser + break-glass | – | – | owner 2026-10-27: `tomigorn-admin` in `authentik Admins` (done in 2a), `akadmin` sealed | – | `ak create_recovery_key 60 akadmin` from the shell |
| Nextcloud (tower) | OIDC `user_uuid`, `cloud-admins` → Nextcloud `admin` group per login | new Nextcloud user (new uuid), admin | `tomigorn` loses admin at next login, files stay | deferred (tower RAM test) | – | Nextcloud local `admin` |

## Effort, phase 2

| Effort | Apps |
|---|---|
| Group change only | Traefik, Cup, Claude-Mockups, VPN status ×2, AdGuard, 6 beefy download apps, 3 fastpi audiobook downloaders |
| Group + one login + delete old app user | Grafana, Dependency-Track, Jellyfin, Audiobookshelf, AudioBookRequest |
| App-side user work (attended) | Portainer (create admin user first), wg-easy (re-link, VPN blip), Home Assistant (owner transfer, Companion tokens) |
| Owner decision first | Seerr owner, Authentik daily admin, HA access for `tomigorn` |
| Deferred | Nextcloud |

## Phase 2 order

1. Config as code first: `provision-media-groups.py` adds `OWNER` (`tomigorn`) to all three streaming groups on every run, so 2b would be undone by the next run. Change it to put `tomigorn` in `streaming-users` + `streaming-requesters` and `tomigorn-admin` in the admin group (test first).
2. DB snapshot (`pg_dump`, `pg_restore -l` check), as before phase 1.
3. 2a: add `tomigorn-admin` to `homelab-admins` + `streaming-admins` (+ `streaming-users`, `streaming-requesters` for Jellyfin/Seerr/ABR admin); Portainer user; log in once per app and tick the Verify column.
4. 2b, one group at a time, `homelab-admins` last: remove `tomigorn`, end its sessions, verify each app both ways.
5. wg-easy and HA owner transfer in an attended window (VPN blip, HA stop).

Rollback of any step: re-add `tomigorn` to the group (instant for the gate; Jellyfin/ABS/ABR re-promote at next sign-in). Full rollback: restore the `pg_dump`. Last resort: `akadmin` via `ak create_recovery_key`.

## Phase 2a state (2026-10-27)

- `tomigorn-admin`: `authentik Admins`, `homelab-admins`, `streaming-admins`, `streaming-users`, `streaming-requesters` (`provision-media-groups.py` `MEMBERS`, `REMOVE_EXTRA = False`). `tomigorn` unchanged (six groups).
- `PolicyEngine`: `tomigorn` passes all 35 apps; `tomigorn-admin` all but `nextcloud` + `nextcloud-wake` (phase 3).
- Claims checked per provider: `groups` carries the admin groups; ABS `groups: [admin]`, ABR `abr_groups: [admin]`.
- App side: Jellyfin `AdministratorGroup=streaming-admins`, `UserGroup=streaming-users`; ABS auto-register, match by email, group claim `groups`; DT teams from `groups`; Grafana `GrafanaAdmin` from `homelab-admins`. All create a new `tomigorn-admin` user at the first login.
- Do NOT open Requests (Seerr) as `tomigorn-admin` before the transfer: it would create a separate Seerr user (the transfer script deletes it again only if it owns no requests).

## Phase 2b runbook

Before: every 2a login ticked, `pg_dump` (`backups/…-pre-admin-split-2b.dump`, `pg_restore -l`), canary green. Under `flock /home/pi/.batch-locks/fastpi-sso.lock`. Order matters: HA first (its new gate must exist before `tomigorn` leaves `homelab-admins`).

| # | Step | Commands | Verify | Rollback |
|---|---|---|---|---|
| 1 | HA + Grafana gate for normal users | `provision-media-groups.py` (`HOMELAB_USERS`, `USER_APPS`): group `homelab-users` + `tomigorn`, bindings on `home-assistant` and `grafana` (next to `homelab-admins`); HA `configuration.yaml` `auth_oidc.roles.user: homelab-users`; Grafana `ALLOWED_GROUPS` + Viewer mapping | `PolicyEngine(home-assistant, tomigorn)` passes | delete binding + group, revert yaml |
| 2 | HA owner transfer | after `tomigorn-admin` logged in once (new HA user, admin): `docker compose stop homeassistant`; `cp -a config/.storage/auth{,.bak-admin-split}`; in `.storage/auth` move `is_owner: true` to the `tomigorn-admin` user, set the `Tomigorn` user `group_ids: ["system-users"]`; `docker compose up -d` | as `tomigorn-admin`: Settings → People → Users shows it Owner + Administrator; as `tomigorn` (and the Companion app): dashboards work, no Settings → System | stop, restore `.storage/auth.bak-admin-split`, start |
| 3 | wg-easy re-link (VPN tunnels drop ~3 s) | `cp -a wg-easy-v15/wg-easy.db{,.bak-admin-split}`; `docker compose stop wg-easy`; `sqlite3 wg-easy-v15/wg-easy.db "UPDATE users_table SET oauth_id='<tomigorn-admin uid>', email='<admin email>' WHERE id=1"` (uid = `User.uid`, the `hashed_user_id` sub); `docker compose up -d`; VPN peers reconnect | `tomigorn-admin` opens wg-easy as `admin`; a VPN client handshakes again | stop, restore `.bak-admin-split`, start |
| 4 | Seerr B (beefy, Seerr stopped) | needs the Jellyfin user `tomigorn-admin` (2a login). `sudo docker compose stop seerr`; `sudo sqlite3 /srv/appdata/seerr/db/db.sqlite3 ".backup /srv/appdata/seerr/db/db.sqlite3.bak-admin-split"`; `.parameter set` lines (see SQL header) + `admin-split-seerr-transfer.sql` piped to `sudo sqlite3 …/db.sqlite3`; start | script prints id 1 `tomigorn-admin` perms 2, new id `tomigorn` 8352 with his requests; `/api/v1/user`; Holy Grail login: `tomigorn-admin` sees Settings, `tomigorn` sees his requests, no Settings; Settings → Jobs → Jellyfin recently added scan runs | stop, copy `.bak-admin-split` back, start |
| 5 | Remove admin groups from `tomigorn` | `REMOVE_EXTRA = True` (+ its test), run `provision-media-groups.py`: `tomigorn` loses `streaming-admins` + `homelab-admins`; Directory → Users → tomigorn → Sessions → delete all; `app-cache-on-group-change.sh --force` | `PolicyEngine`: `tomigorn` fails every admin app, passes jellyfin(-wake), tracker(-login), requests(-login), books(-login), audiobookshelf, home-assistant, nextcloud, wiki, specs, avatar; canary green | `REMOVE_EXTRA = False`, re-add both groups (`ak shell`), or restore the dump |
| 6 | Demote inside the apps | Jellyfin and ABS via their admin API (an existing app session never re-reads the claims: Jellyfin `IsAdministrator=false`, ABS `PATCH /api/users/<id> {"type":"user"}`); ABR: `tomigorn` signs in once (role `trusted`) | as `tomigorn`: no Jellyfin Dashboard, no ABS Settings, ABR gear = own account only | re-add group + API back |
| 7 | Delete old admin users | Grafana: Administration → Users → `tomigorn` delete; DT: Administration → Access → OpenID Connect users → `tomigorn` delete; Portainer: Users → `tomigorn` (id 2) delete | lists show only `tomigorn-admin` (+ local break-glass) | recreate (Portainer: as initial admin) |
| 8 | Floppy ABS link | shell only (edge blocks the UI path): ABS admin → Users → `floppy-sync` (Admin) + API key `floppy-sync` acting as it; beefy `sudo Floppy/scripts/abs-push.py store-key` (one service key for all users, refuses any other key; Floppy gets pushed progress, holds no key) | progress syncs | delete the `floppy-sync` key in ABS |
| 9 | Docs | README "Admin account", this table's state column, memory | – | – |


## Owner decision 2026-10-27 (before 2b)
- Group name for the everyday account is **`homelab-users`** (not `home-users`). `tomigorn` is in `homelab-users`; `tomigorn-admin` in `homelab-admins`.
- `homelab-users` grants: Home Assistant as a normal user AND Grafana as Viewer (everyday account keeps read access to the dashboards). Admin rights stay with `homelab-admins`.

## Phase 2b state (2026-10-27, log `~/reports/2026-10-27/admin-split-2b-log.md`)

Backup: `backups/authentik-db-2026-10-27-pre-admin-split-2b.dump` (`pg_restore -l` ok), canary green before and after.

| # | State |
|---|---|
| 1 | done: group `homelab-users` (`tomigorn`), bindings on `home-assistant` + `grafana`, HA `roles.user: homelab-users`, Grafana Viewer mapping |
| 2 | done: owner = "Tomigorn (admin)", "Tomigorn" = `system-users`; person pictures set; backup `.storage/auth.bak-admin-split`, `person.bak-admin-split`, `~/backups/home-assistant/ha-storage-2026-10-27-pre-admin-split-2b.tgz` |
| 3 | done: wg-easy user 1 linked to `tomigorn-admin` (oauth_id = its uid, email = admin address); backup `wg-easy-v15/wg-easy.db.bak-admin-split` |
| 4 | done: Seerr id 1 = `tomigorn-admin` (perms 2, 0 requests), id 7 = `tomigorn` (8352, 14 requests, Holy Grail link moved); backup `/srv/appdata/seerr/db/db.sqlite3.bak-admin-split` (beefy); Jellyfin recently-added scan ok |
| 5 | done: `REMOVE_EXTRA = True`, `tomigorn` left `homelab-admins` + `streaming-admins`, its 4 Authentik sessions deleted, app cache cleared; PolicyEngine: `tomigorn` fails all 19 admin apps, passes the 16 everyday apps; canary green |
| 6 | Jellyfin done (`IsAdministrator=false` via API, also covers app/Quick Connect sessions); ABS done 2026-10-27 22:51 (`PATCH /api/users/<id> {"type":"user"}` with an admin key, backup `audiobookshelf/config/absdatabase.sqlite.bak-admin-split`; 22 progress rows, all libraries, unchanged; see "ABS: why it did not demote"); ABR: already `trusted` (OIDC login 22:42), its gear is the own-account page (API keys only) |
| 7 | Grafana: `tomigorn` kept as Viewer (owner decision; demoted in `grafana.db`, backup `grafana.db.bak-admin-split` in the volume); Portainer: user `tomigorn` deleted (backup `~/backups/portainer/portainer-2026-10-27-pre-admin-split.tar.gz`); DT: OIDC user `tomigorn` still there, delete by hand as `tomigorn-admin` (local DT `admin` login refused the stored password) |
| 8 | open, by hand: no UI path (edge 403 on `/import/audiobookshelf/`, SSRF mitigation); `tomigorn-admin` in ABS → Users → `floppy-sync` (Admin, done 2026-10-27) + Settings → API Keys → key `floppy-sync` acting as `floppy-sync`, then on beefy `sudo ~/Projects/Docker/Floppy/scripts/abs-push.py store-key` (Floppy README "Audiobookshelf push"); all same-named users sync automatically |

## ABS: why it did not demote (2026-10-27)

ABS 2.37.2 applies the `groups` claim only in the OIDC callback (`OidcAuthStrategy.setUserGroup`: downgrades admin → user fine, refuses to downgrade `root`). It keeps its own refresh-token sessions (30 days, rolling, one per browser/app): `tomigorn` had 5, so opening ABS after the group change reused a session and never reached Holy Grail. Signing in to Holy Grail again does not help.

For phase 3 / future demotions in ABS: after the group change, set the type at once with the admin API (`PATCH /api/users/<id>` `{"type":"user"}`, changes only the type, progress and permissions stay), or log out in ABS and sign in via Holy Grail. The same applies to promotions. Jellyfin was demoted via API for the same reason (Quick Connect / app sessions).

