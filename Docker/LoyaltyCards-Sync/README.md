# LoyaltyCards-Sync

Self-hosted [PocketBase](https://pocketbase.io/) v0.39.1 backend for the LoyaltyCards PWA. Provides card data sync with owner isolation and optional TOTP 2FA.

## What this is

- PocketBase REST API backend (SQLite, single binary)
- `cards` collection — owner-isolated: each user can only read and write their own cards (enforced by PocketBase collection rules)
- Custom TOTP 2FA routes for enrolling, enabling, disabling, and using time-based one-time passwords
- Long-lived auth tokens (~3 years) so the PWA stays logged in across browser sessions; only an explicit logout ends a session

## Bootstrap

The superuser is auto-created on first boot from environment variables:

| Variable | Description |
|---|---|
| `PB_ADMIN_EMAIL` | Admin (superuser) email |
| `PB_ADMIN_PASSWORD` | Admin (superuser) password |
| `PB_PUBLIC_URL` | Public HTTPS URL, e.g. `https://loyalty-sync.holy-grail.ch` |

Copy `.env.example` to `.env` and fill in the values. The `.env` file is gitignored.

PocketBase data is stored in the `pb_data` Docker volume. Collection schema migrations run automatically on startup.

## How to run

```bash
docker compose up -d --build
```

The API is available at port 8090. The admin dashboard is at `/_/`.

## Endpoints

### Standard PocketBase REST API

All standard PocketBase endpoints apply. The relevant collection:

**`/api/collections/users/records`** — user registration, profile updates  
**`/api/collections/cards/records`** — CRUD for loyalty cards (owner-scoped; auth required)

Records in the `cards` collection are filtered by owner so a user can only access their own cards. See [PocketBase REST API docs](https://pocketbase.io/docs/api-records/) for full query/filter syntax.

### Custom TOTP routes

All routes are under `/api/loyalty/totp/`. Requests and responses use JSON.

#### `POST /api/loyalty/totp/required`

Check whether a user has TOTP enabled (used before the login screen to decide whether to show the 2FA field). No auth required.

Request:
```json
{ "identity": "user@example.com" }
```
Response:
```json
{ "required": true }
```

#### `POST /api/loyalty/totp/login`

Authenticate with email/username + password, plus optional TOTP code if enabled. Returns a standard PocketBase auth response.

Request:
```json
{ "identity": "user@example.com", "password": "...", "code": "123456" }
```
(`code` is optional when `required` is `false`)

Response (200):
```json
{ "token": "<jwt>", "record": { ... } }
```

#### `POST /api/loyalty/totp/setup`

Begin TOTP enrollment. Returns a secret and an `otpauth://` URL for scanning with an authenticator app. Auth required (Bearer token).

Response:
```json
{ "secret": "BASE32SECRET", "otpauthUrl": "otpauth://totp/..." }
```

#### `POST /api/loyalty/totp/enable`

Confirm TOTP enrollment by verifying the first code from the authenticator. Auth required.

Request:
```json
{ "code": "123456" }
```
Response:
```json
{ "enabled": true }
```

#### `POST /api/loyalty/totp/disable`

Disable TOTP by verifying the current code. Auth required.

Request:
```json
{ "code": "123456" }
```
Response:
```json
{ "enabled": false }
```

## Auth

Users authenticate via:
- **Email/password** (+ TOTP if enabled) via `/api/loyalty/totp/login`
- **Google OAuth2** — configure provider credentials in the admin dashboard under Collections → users → Auth providers, plus set the client ID/secret in the PocketBase settings; no restart required

Auth tokens are set to ~3 years (PocketBase's maximum allowed duration). The PWA auto-refreshes tokens in the background; the only way a session ends is an explicit client-side logout (clearing the stored token).

## CORS

PocketBase is permissive by default and allows cross-origin requests. The PWA at `https://loyalty-cards.holy-grail.ch` uses Bearer token auth (not cookies), which is safe across origins without additional CORS configuration.

## Network

The container joins the `traefik_proxy` external Docker network. Traefik handles TLS termination and routing via Cloudflare Tunnel. No ports are published directly to the host.
