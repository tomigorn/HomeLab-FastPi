# LoyaltyCards-Sync — Deploy checklist (USER-GATED)

The backend builds, tests green, and runs locally. The steps below put it live on a new
public subdomain. They are intentionally NOT performed automatically — review and run them
on your cadence. Nothing here has been applied to live infra yet.

## Before you start — one decision: open signup
Pocketbase allows **open user registration by default** — anyone who finds
`loyalty-sync.holy-grail.ch` could create an account (they still can't see anyone else's
cards; the `cards` collection is owner-isolated). For a private/family service you may want to
restrict this. In the Pocketbase admin UI → `users` collection → "Options", either:
- leave open signup ON (convenient, accept that strangers could register accounts), or
- turn the create rule off / restrict it so only you create accounts (then add family via admin).

## Steps
1. **Cloudflare Tunnel:** add a public hostname `loyalty-sync.holy-grail.ch` pointing at the
   Traefik service (same pattern as the existing `loyalty-cards.holy-grail.ch` entry).
2. **Traefik route:** copy `deploy/loyalty-sync.yml` →
   `/home/pi/Projects/Docker/Traefik/traefik/dynamic/loyalty-sync.yml`.
3. **PWA CSP:** in `/home/pi/Projects/Docker/Traefik/traefik/dynamic/loyalty-cards.yml`,
   add the sync origin to `connect-src` so the PWA may call the backend:
   ```
   connect-src 'self' https://img.logo.dev https://icon.horse https://icons.duckduckgo.com https://loyalty-sync.holy-grail.ch;
   ```
4. **Start the backend:**
   ```bash
   cd /home/pi/Projects/Docker/LoyaltyCards-Sync && docker compose up -d --build
   ```
5. **Verify:** `curl -s -o /dev/null -w '%{http_code}\n' https://loyalty-sync.holy-grail.ch/api/health` → `200`.
6. **Admin once:** log into `https://loyalty-sync.holy-grail.ch/_/` with the
   `PB_ADMIN_EMAIL`/`PB_ADMIN_PASSWORD` from `.env`, confirm the `cards` collection exists,
   set the open-signup decision above, and (optionally) configure the **Google OAuth2**
   provider — set `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` in `.env` and the provider in the
   admin UI; redirect URL `https://loyalty-sync.holy-grail.ch/api/oauth2-redirect`.

## Notes
- Data (SQLite + uploaded files) lives in the `pb_data` Docker volume — back it up like other stateful volumes.
- The admin console (`/_/`) is reachable on the subdomain; it is protected by the admin
  credentials. Consider an extra Traefik IP/auth restriction if you want it non-public.
- This is Phase A only (backend). The PWA does not call it yet — that's Phases B (auth UI) and
  C (sync engine), which are planned separately.
