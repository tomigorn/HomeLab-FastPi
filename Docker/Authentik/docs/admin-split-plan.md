# Admin split: `tomigorn` (everyday) + `tomigorn-admin` (admin)

Least privilege: the everyday account keeps watching, listening, requesting; every admin right moves to a separate account with its own password + MFA. `akadmin` stays the Authentik break-glass superuser, untouched.

| Phase | What | State |
|---|---|---|
| 1 | inventory, this plan, create `tomigorn-admin` (`scripts/provision-admin-account.py`), owner sets password + MFA via a one-time recovery link | done 2026-10-27 |
| 2a | add `tomigorn-admin` to the admin groups, set up per-app admin users, verify each app as `tomigorn-admin` | open |
| 2b | only after 2a verified everywhere: remove `tomigorn` from the admin groups, demote/delete old admin users in the apps | open |
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
| Portainer | CE OAuth, auto-provisioning OFF: admin = pre-created Portainer user `tomigorn` | login refused until a Portainer user `tomigorn-admin` exists | Authentik gate refuses `tomigorn` | 2a: as `tomigorn` in Portainer (or initial admin over `ssh -L 9443`): Users → add `tomigorn-admin`, role Administrator; log in via Holy Grail as it. 2b: delete Portainer user `tomigorn` | `tomigorn-admin` sees both environments | initial admin via `ssh -L 9443:127.0.0.1:9443 fastpi` → `/#!/internal-auth`; `helper-reset-password` |
| wg-easy | OIDC, auto-register off; one user `admin` (id 1) linked by `oauth_id` to `tomigorn` | refused (no linked user) | gate refuses `tomigorn`; nobody can log in until re-linked | 2a+2b together (one user only): back up `wg-easy-v15/wg-easy.db`, stop container (drops VPN tunnels ~3 s, attended), set user 1 `email` = admin plus-address, `oauth_id`/`oauth_provider` = NULL, start; log in as `tomigorn-admin` → links by email | wg-easy opens as `tomigorn-admin`; `tomigorn` refused | restore the db backup; `DISABLE_PASSWORD_AUTH=false` + `cli db:admin:reset` (compose comments) |
| Home Assistant | `hass-oidc-auth`, roles admin+user = `homelab-admins`, set at FIRST login only; owner flag = OIDC user "Tomigorn" | first login creates a new HA admin user + person | Authentik gate refuses new logins, but HA refresh tokens (Companion app!) of `tomigorn` keep working until revoked | 2a: login once as `tomigorn-admin`. Owner transfer: HA stopped, back up `config/.storage/auth`, move `is_owner` to the new user. 2b: decide whether `tomigorn` keeps HA as non-admin (needs a non-admin group mapped to `roles.user`) or loses it (revoke refresh tokens, deactivate) | new user shows Owner + Administrator | restore `.storage/auth`; shell recovery: re-add `homeassistant` auth provider (HA README) |
| Dependency-Track (beefy) | forward auth + OIDC `dt-login`, gate `homelab-admins`; user = `preferred_username`, teams synced from `groups` at every login (`homelab-admins` → Administrators) | new DT user `tomigorn-admin` in Administrators | gate refuses `tomigorn`; old DT user stays | 2a: login once. 2b: delete DT user `tomigorn` | `tomigorn-admin` in team Administrators | local `admin` (beefy `secrets/dt_admin_password`) |
| Radarr, Sonarr, Prowlarr, Bazarr, SABnzbd, qBittorrent (beefy) + qBit/SAB/Prowlarr audiobooks (fastpi) | forward auth only, gate `streaming-admins`; apps have no own users | opens | refused | 2a: add to `streaming-admins`. 2b: remove `tomigorn` | each opens as `tomigorn-admin` | re-add group; LAN `ssh -L` to the app port |
| Jellyfin (beefy) | OIDC plugin, sign-in gate `streaming-users` (Authentik binding), admin = direct `streaming-admins` membership, set/removed at EVERY sign-in; user matched by username | needs `streaming-users` too to pass the gate; then a new Jellyfin user `tomigorn-admin`, administrator, empty history | `tomigorn` loses administrator at next sign-in; history, favourites, Quick Connect stay | 2a: add to `streaming-users` + `streaming-admins`, sign in once (wake beefy), restrict its library access if wanted. 2b: remove `tomigorn` from `streaming-admins`, sign in once as `tomigorn` (demotion applies on sign-in) | Dashboard reachable as `tomigorn-admin`, not as `tomigorn` | re-add group + sign in; sqlite recovery (Jellyfin README) |
| Audiobookshelf | OIDC, auto-register on, match existing by email, `groups` claim → `admin`/`user` at every login; gate `streaming-users` OR policy `audiobookshelf-access` (admins pass alone); local `root` user exists, password login off | new ABS user `tomigorn-admin`, type admin | `tomigorn` becomes type `user` at next login, progress/bookmarks stay; bonus: Floppy may then link `tomigorn` (it refuses ABS admins) | 2a: add to `streaming-admins` (no `streaming-users` needed), log in once. 2b: remove `tomigorn`, log in once as `tomigorn`, check its library access | `tomigorn-admin` sees Settings; `tomigorn` sees no Settings, progress intact | re-add group; enable local auth in DB + `root` |
| AudioBookRequest | OIDC, gate `streaming-requesters`; `abr_groups` claim: `streaming-admins` → admin | needs `streaming-requesters` to pass the gate; new ABR user `tomigorn-admin`, admin | `tomigorn` becomes `trusted` (if ABR re-reads the role at login: verify) | 2a: add to `streaming-requesters`, log in once. 2b: remove `tomigorn`, log in once, check role | ABR Settings as `tomigorn-admin` only | `ABR_FORCE_LOGIN_TYPE=forms` + `abr-root` (ABR README) |
| Seerr (beefy) | OIDC `requests-login`, gate `streaming-requesters`; owner = user id 1 = `tomigorn` (Jellyfin-type, linked); id 1 always has every permission, no ownership transfer | needs `streaming-requesters`; first press creates a new Seerr user with default permissions (new user login on) | nothing: Seerr permissions are local; id 1 stays owner | ❓ owner decision: A) accept `tomigorn` stays Seerr owner (in-app only, low blast); or B) relink id 1 to `tomigorn-admin` and give `tomigorn` a new requester user (requests move by sqlite update, attended) | as chosen | Seerr settings backup + `linked_accounts` sqlite (Seerr README) |
| Floppy / Tracker (beefy) | OIDC, gate `streaming-users`; no admin user at all | nothing to do | nothing | none | – | – |
| Authentik itself | `tomigorn` is not superuser; `akadmin` (`authentik Admins`) = superuser + break-glass | – | – | ❓ owner decision: make `tomigorn-admin` the daily Authentik admin (`authentik Admins`) and keep `akadmin` sealed, or keep using `akadmin` | – | `ak create_recovery_key 60 akadmin` from the shell |
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
