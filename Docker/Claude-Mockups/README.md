# Claude-Mockups

A private space (Holy Grail SSO only) for hosting throwaway UI mockups and demos so
they can be reviewed remotely (not just on `localhost`).

- **URL:** https://claude-mockups.holy-grail.ch (Holy Grail / Authentik SSO login, group `homelab-admins`)
- **Server:** a single `caddy:alpine` container serving static files with a
  styled directory listing (see `Caddyfile`). Caddy does no auth.
- **Content:** one subfolder per demo under `www/`.

## How it's wired

```
Internet
  → Cloudflare edge + Tunnel (cloudflared)        public hostname route
  → https://192.168.1.2:443  (this Pi's Traefik)  No TLS Verify: On
  → Traefik router  Host(`claude-mockups.holy-grail.ch`)
       middlewares: authentik@file (forward auth) → default-rate-limit → secure-headers
       (TLS terminates here; companion router claude-mockups-outpost serves
        /outpost.goauthentik.io/ straight to the Authentik outpost)
  → http://claude-mockups:80  (the Caddy container, on the traefik_proxy network)
       Caddy serves:
  → /srv  ==  ./www
```

Files that make this work:

| File | Purpose |
|---|---|
| `docker-compose.yaml` | the Caddy container and the answer-inbox |
| `Caddyfile` | serves `/srv` with directory browse (no auth: Traefik does it) |
| `.env` | only `COMPOSE_PROJECT_NAME` (no secrets any more) |
| `www/` | demo content, one subfolder per mockup (gitignored) |
| `assets/` | durable client lib for interactive answers (`answer.js`/`.css`), served at `/_assets/*` |
| `inbox/server.js` | tiny dependency-free `answer-inbox` service (records selections) |
| `answers/` | received selections, `<token>.json` (gitignored) — Claude reads these |
| `wait-for-answer.sh` | blocks until `answers/<token>.json` arrives, then prints it (Claude runs this in the background) |
| `../Traefik/traefik/dynamic/claude-mockups.yml` | Traefik route: TLS, rate-limit, headers |

## Add a demo

```bash
mkdir -p www/my-demo
$EDITOR www/my-demo/index.html
```

Reach it directly at https://claude-mockups.holy-grail.ch/my-demo/.
Delete the folder to remove it. No restart needed (the volume is live).

### Root redirect (the "current" demo)

The bare site (`https://claude-mockups.holy-grail.ch/`) auto-redirects to the
current demo via `www/index.html` — a small redirect file. To point the root at
a different demo, edit both target paths in `www/index.html`:

```html
<meta http-equiv="refresh" content="0; url=./my-demo/">
<script>location.replace("./my-demo/");</script>
```

It's served from the live volume, so the change is instant — no restart.

## Interactive answers (pick → Confirm → back to Claude)

A mockup can let the user **choose an option and press Confirm, and the choice is
sent straight back to Claude** — no returning to the terminal to retype it.

How it's wired:

```
browser  --POST /_inbox/submit-->  Caddy (after Traefik forward auth)  --strip /_inbox-->  answer-inbox:8080
                                                                              writes answers/<token>.json
Claude (on the Pi)  <--reads--  answers/<token>.json   (and waits for it to appear)
```

- `answer-inbox` is a tiny dependency-free Node service on an **internal-only**
  network — never exposed via Traefik. It only accepts a validated `token`
  (`[A-Za-z0-9_-]{6,64}`, which also blocks path traversal) and atomically
  writes `answers/<token>.json`.
- The POST rides the page's Authentik session cookie (same origin), so it's
  gated exactly like the rest of the site. If the SSO session expires while a
  page is open, the POST gets a cross-origin 302 and fails: reload the page.

**Make a question page** — give the `<body>` a unique token, mark options with
`data-choice`, add a Confirm button, and include the client lib:

```html
<link rel="stylesheet" href="/_assets/answer.css">
<body data-claude-token="UNIQUE_TOKEN_HERE">
  <div data-options>                          <!-- add data-multiselect to allow many -->
    <div data-choice="a">Option A</div>
    <div data-choice="b">Option B</div>
  </div>
  <button data-confirm disabled>Confirm</button>
  <span data-indicator></span>                <!-- optional live status -->
  <textarea data-note></textarea>             <!-- optional free-text note -->
  <script src="/_assets/answer.js" defer></script>
</body>
```

Working reference: `www/_example-question/index.html`
(live at https://claude-mockups.holy-grail.ch/_example-question/).

**Claude's loop per question:**

1. Generate a unique token, e.g. `openssl rand -hex 8`.
2. Write `www/<demo>/index.html` from the snippet above (mockup + options +
   Confirm + the token), and point the root redirect at it if appropriate.
3. Give the user the demo URL.
4. **Watch in the background** — launch `./wait-for-answer.sh <token>` with
   `run_in_background: true`. It blocks until `answers/<token>.json` appears,
   then prints it (exit 0); `TIMEOUT` + exit 1 if nothing arrives in time
   (default 30 min). Claude never ends its turn waiting for the user to report
   back — the user's Confirm wakes it.

## Deploy / run

```bash
cd ~/Projects/Docker/Claude-Mockups
docker compose up -d
```

The Traefik route is picked up automatically (Traefik watches `/dynamic`).

## One-time setup (already done, kept here for reference)

1. **Cloudflare dashboard → Zero Trust → Networks → Tunnel `fastpi` → Published
   application routes → Add:** hostname `claude-mockups.holy-grail.ch`,
   service `HTTPS` → `192.168.1.2:443`, **No TLS Verify: On**.
   Cloudflare auto-creates the DNS record.
2. **Authentik side (Holy Grail SSO):** provider `claude-mockups-proxy` and application
   `claude-mockups` (bound to group `homelab-admins`) come from section 7 of
   `../Authentik/scripts/provision-admin-sso.py`; the dashboard look from
   `../Authentik/scripts/dashboard-look.py`. See "Admin SSO" in `../Authentik/README.md`.

   **Recovery when Authentik is down (server shell only):** read `www/` and `answers/`
   directly; or temporarily add `basic_auth { user <caddy-hash-password hash> }` to the
   `Caddyfile` site block and add a temporary Traefik router without `authentik@file`
   (the dynamic dir is watched), then undo both.

## Security notes

- Whole subdomain is gated by **Authentik forward auth** (Holy Grail SSO, group
  `homelab-admins`) at Traefik. Caddy and answer-inbox have no host ports and are
  only reachable through Traefik / the internal network.
- Secure headers (HSTS, nosniff, frameDeny, referrer-policy) are applied by
  Traefik, but **no strict CSP** — mockups legitimately use CDNs and inline
  scripts/styles.
- The container serves the `www` volume **read-only** and runs with
  `no-new-privileges`. No server-side code, just static files.
