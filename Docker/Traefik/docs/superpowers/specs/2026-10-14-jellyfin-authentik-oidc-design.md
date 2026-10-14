# Jellyfin ← Authentik login (OIDC plugin) — design

Date: 2026-10-14 · Status: approved in chat ("go with your recommendation") · Component: Jellyfin on beefy
(`lscr.io/linuxserver/jellyfin:12.1…`, config `/srv/appdata/jellyfin`), Authentik on fastpi.

## Goal

Every household member logs in to Jellyfin with their Authentik account; nobody gets or uses a
Jellyfin password. The local `admin` created in the setup wizard stays as the only break-glass
account. TV/phone apps log in via Jellyfin's Quick Connect (code approved from the signed-in web UI).

## Why this plugin

- The plugin named in `2026-10-06-authentik-sso.md` (9p4 `SSO-Auth`) is **archived** and its last
  build targets Jellyfin 10.11 ABI; we run 12.1. Jellyfin has no built-in OIDC (PR #17271 closed
  unmerged 2026-10-02).
- **edmogeor/jellyfin-plugin-oidc** (GPL-3.0, releases 2026-10-12/13, `targetAbi 12.0.0.0`) is the
  only maintained option for Jellyfin 12: Authentik preset, flat `groups` claim → allowed/admin
  groups, automatic provisioning with random unusable passwords, password-login modes, self-service
  linking, documented emergency recovery. Risk accepted: very young project; mitigated by the
  break-glass admin and the documented recovery (`plugins/configurations/Jellyfin.Plugin.Oidc.xml`
  `Enabled=false` + SQL reset of `AuthenticationProviderId`).

## Decisions

| Setting | Value | Why |
|---|---|---|
| Provider | Authentik, issuer `https://sso.holy-grail.ch/application/o/jellyfin/` | existing app `jellyfin` / provider `jellyfin-oidc` |
| Callback | `https://jellyfin.holy-grail.ch/oidc/callback` | plugin's URL (old `/sso/OID/redirect/authentik` removed) |
| Public URL override | `https://jellyfin.holy-grail.ch` | behind Traefik/Cloudflare |
| Allowed group | `streaming-users` | existing group (same as the wake page) |
| Administrator group | `streaming-admins` | existing group |
| Group claim / username claim | `groups` / `preferred_username` | Authentik's default `profile` scope provides both |
| Require verified email | on; Authentik gets a custom `email` scope mapping returning `email_verified: True` | Authentik's default mapping says `False`; accounts are invite-only, emails are real |
| Automatic linking | EmailToUsername (default) | no pre-existing Jellyfin users except `admin` (no email) → nothing to collide with |
| Provisioning username | username claim | Jellyfin users named like Authentik users |
| Password login mode | **DisableForLinkedUsersOnly** | provisioned users get random, disabled passwords; the unlinked local `admin` keeps its password as break-glass |
| Redirect sign-in page to provider | off (only available in disable-for-all mode) | login page shows the Authentik button + the local form for `admin` |
| Self-service linking | on (default) | lets `admin` or a future local user attach an Authentik identity |
| Quick Connect | already enabled on the server (`QuickConnectAvailable=true`) | TV/phone apps |
| RP-initiated logout | off | Jellyfin logout stays local (TV sessions unaffected) |

## Authentik changes (config lives in the DB; recorded in `2026-10-06-authentik-sso.md` §2.2)

1. `jellyfin-oidc` provider: redirect URI → `https://jellyfin.holy-grail.ch/oidc/callback`
   (replace the old one); keep confidential client, signing key, implicit-consent flow.
2. New ScopeMapping "authentik email (verified)" (scope `email`, expression returning
   `email`/`email_verified: True`), bound to `jellyfin-oidc` instead of the default `email` mapping.
   Only this provider uses it.
3. Throwaway test users for the automated test: `claude-test` (streaming-users) and `claude-admin`
   (streaming-admins), both with TOTP devices; deleted after the test.

## Jellyfin changes (beefy, scripted over SSH)

1. Manual plugin install (Jellyfin's documented way): download
   `oidc-authentication_0.3.1.0.zip` (md5 `c0ba16f62e9269f998549315c79fe07e` from the manifest),
   unzip into `/srv/appdata/jellyfin/plugins/OIDC Authentication_0.3.1.0/` (owner 1000:1000).
2. Config as code: write `/srv/appdata/jellyfin/plugins/configurations/Jellyfin.Plugin.Oidc.xml`
   with the values above (the plugin's `PluginConfiguration` fields; enums by name), client secret
   read from Authentik over the LAN and never printed. Jellyfin restarted (`docker restart jellyfin`);
   plugin load confirmed in the Jellyfin log; the plugin's dashboard page is the source of truth
   afterwards (the file is bind-mounted, so it stays readable on beefy).
3. Also add the plugin repository URL to Jellyfin's catalogue config so updates show in the
   dashboard (`https://raw.githubusercontent.com/edmogeor/jellyfin-plugin-oidc/manifest-release/manifest.json`).

## Traefik

No change needed: `/oidc/*` on the Jellyfin host goes through the catch-all router (gate with
`policy=jellyfin`; a browser callback is a navigation and happens while beefy is awake).

## Testing (run by Claude)

- Playwright + system Chromium, beefy awake: open `https://jellyfin.holy-grail.ch/web/` → click the
  Authentik sign-in button → Authentik (user/password/TOTP) → back in Jellyfin signed in as
  `claude-test`; repeat as `claude-admin` and confirm the Dashboard is reachable.
- Verify on beefy: both users exist in Jellyfin with `AuthenticationProviderId` = the plugin's
  password-disabled provider; `admin` unchanged (default provider).
- Negative: an Authentik user outside both groups is refused.
- Real device: the user signs in with their own Authentik account in a browser; a TV app via Quick
  Connect.
- Cleanup: delete `claude-test`/`claude-admin` in Authentik and in Jellyfin.

## Out of scope

- Nested groups, folder-level access per group (single Movies library).
- Replacing the break-glass admin with Authentik (would need "disable for all users").
