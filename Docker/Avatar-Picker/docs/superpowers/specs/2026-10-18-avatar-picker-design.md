# Avatar Picker — design

Date: 2026-10-18 · Status: approved (user chose approach 1, gallery option A, unique avatars)

## Goal

Netflix-style profile pictures for every Authentik user: pick one picture from a
fixed gallery; nobody else can hold the same picture; the choice shows up in
Authentik itself and in every app that accepts an OIDC `picture` claim.

## Scope

| App | Shows the avatar | How |
|---|---|---|
| Authentik | yes | Avatars setting `attributes.avatar,initials` |
| Jellyfin (beefy, plugin "OIDC Authentication" 0.3.4) | yes, on next sign-in | plugin option `SynchronizeProfileImages=true` |
| Nextcloud (tower, user_oidc 8.11) | yes, on next login | `occ user_oidc:provider authentik --mapping-avatar=picture` |
| Audiobookshelf | no | ABS has no user pictures (not possible) |
| Grafana, Portainer, Home Assistant, Vaultwarden | no | none consume OIDC `picture` |

Out of scope (YAGNI): uploads, admin overrides, per-app pictures, ABS.

## Constraints found in research

- Authentik 2026.8's default `profile` scope emits `picture` = `request.user.avatar`,
  but drops `data:` URIs. So the avatar must be an `https://` URL.
- Authentik media under `/files/media/` needs an expiring token, so it cannot host
  stable avatar URLs; a separate static host is needed.
- Jellyfin plugin: HTTPS URL on a public address or the IdP host, ≤5 MB,
  gif/jpeg/png/webp, no redirects, 10 s timeout.
- Nextcloud: http(s) URL fetched server-side, must be JPG/PNG **and square**.
- Gravatar avatars would be emitted as `picture` too; dropping `gravatar` from the
  Avatars setting removes that (and the privacy leak to gravatar.com).

## Architecture

New project `Docker/Avatar-Picker` on fastpi (one container, Python stdlib only,
same style as the wakers), public hostname `avatars.holy-grail.ch`:

| Path | Auth | Purpose |
|---|---|---|
| `/img/<id>.png` | **public** (separate Traefik router, higher priority) | gallery images; fetched by Jellyfin/Nextcloud servers without a login |
| `/` | Authentik forward auth (`authentik@file`, like cup) | the picker grid |
| `/api/state` (GET) | forward auth | gallery + who holds what (anonymised: only "taken"/"yours") |
| `/api/pick` (POST `{id}`) | forward auth | set the caller's avatar |
| `/outpost.goauthentik.io/` | — | routed to `authentik@file` (forward-auth callback) |

The caller's identity comes from the `X-authentik-uid` / `X-authentik-username`
headers that the forward-auth middleware sets; Traefik strips client-supplied
copies (forwardAuth `authResponseHeaders` overwrite them).

### Gallery

~24 square 512×512 PNGs: Microsoft **Fluent Emoji** animals (3D style, MIT
licence; licence verified and credited in `LICENSES.md`) centred on a soft
coloured background, one colour per animal. Generated once by a script in the
repo (`scripts/build-gallery.py`) from the upstream PNGs; output committed under
`app/img/`. `app/gallery.json` lists `{id, name, file}`.

### Saving and uniqueness

- The service holds an Authentik API token of a dedicated service account
  `avatar-picker` with an RBAC role limited to `view_user` + `change_user`.
  Token in a gitignored secrets file, never in git.
- `POST /api/pick`: under a process-wide lock, list users (API, paged), check that
  no *other* user has `attributes.avatar == <url>`; if free, PATCH the caller's
  user with `attributes.avatar = https://avatars.holy-grail.ch/img/<id>.png`
  (merge, keeping other attributes). Taken → HTTP 409 "just taken".
- The old picture is freed implicitly (nobody holds it any more). Deleted or
  deactivated users: inactive users still hold theirs (simple, predictable).

### Authentik / app configuration

- System → Settings → Avatars: `attributes.avatar,initials`.
- Jellyfin plugin config: `SynchronizeProfileImages=true`.
- Nextcloud: `--mapping-avatar=picture` (default claim name is `avatar`).
- Cloudflare tunnel: public hostname `avatars.holy-grail.ch` → `https://192.168.1.2:443`
  (user, dashboard). AdGuard rewrite to 192.168.1.2 for LAN/VPN.

## Error handling

- Authentik API unreachable → page shows "can't load / can't save right now";
  nothing written.
- Race on the same picture → second save gets 409 with a friendly message.
- Unknown id / missing identity header → 400 / 401, nothing written.
- Image route never errors on auth (public static files).

## Security

- Picker and API only behind Authentik; images public by design (they are
  generic illustrations, contain nothing personal).
- Container: non-root, `cap_drop: ALL`, read-only root FS, memory limit,
  `no-new-privileges`; secrets file mounted read-only.
- Token blast radius: can edit user objects. Mitigated by least-privilege role,
  no inbound path except Traefik + Authentik, and code that only ever writes the
  caller's own `attributes.avatar`.
- The API never returns other users' names, only "taken".

## Testing

- Unit tests (stdlib `unittest`) for: uniqueness decision, attribute merge, gallery
  validation (square, PNG, ≤5 MB), header-identity parsing.
- Integration: pick → Authentik user attribute set → `/application/o/userinfo/`
  `picture` returns the URL; Nextcloud and Jellyfin show it after a login.
- Smoke-test script gets checks for `/img/` (200 public) and `/` (302 to SSO).

## Addendum v1.3.0 (2026-10-18): pop-culture rows and the local pack

- Six rows added (18 x 9): "Classic cartoons (public domain)" (committed; US
  public domain only, see LICENSES.md) and five pop-culture rows (movies, TV &
  cartoons, anime, video games, memes).
- The pop-culture art is copyrighted, so it lives in a **local pack**:
  `app/img-local/` (gitignored; still in the Docker build context, so it is baked
  into the private image). Entries carry `"pack": "local"` in `gallery.json`.
- The server serves both dirs under the same `/img/<id>.png` URL and, at start-up,
  hides any avatar whose file is missing (and any row left empty), so a fresh
  clone or CI run works without the pack. `build-gallery.py --only <rows>`
  re-fetches it.
- Memes row is exempt from the strict f/m/n order (it happens to be balanced).

## Addendum v1.4.0 (2026-10-19): row order, bigger pop-culture rows, colours

- Rows reordered as the user asked: movies, TV & cartoons, anime, video games,
  classic storybook, illustrated people, flat emoji, art classics, memes,
  cartoon & sketch, then the rest, with a new "Colours" row last. Group ids and
  all existing avatar ids are unchanged.
- Rows are now any multiple of 9 (desktop keeps 9 per line and wraps): the four
  pop-culture rows have 27 each, flat emoji / art classics / memes 18 each.
  279 avatars in total (144 committed, 135 in the local pack).
- Colours row: 18 solid colours, gradients and rainbows generated with Pillow in
  `build-gallery.py` (no downloads, nothing third-party).
- Memes stay animal/drawn-character only; the memes and colours rows are exempt
  from the f/m/n interleave.
