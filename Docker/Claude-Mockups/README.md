# Claude-Mockups

A private, password-protected space for hosting throwaway UI mockups and demos so
they can be reviewed remotely (not just on `localhost`).

- **URL:** https://claude-mockups.holy-grail.ch (behind HTTP basic auth)
- **Server:** a single `caddy:alpine` container serving static files with a
  styled directory listing and enforcing basic auth (see `Caddyfile`).
- **Content:** one subfolder per demo under `www/`.

## How it's wired

```
Internet
  → Cloudflare edge + Tunnel (cloudflared)        public hostname route
  → https://192.168.1.2:443  (this Pi's Traefik)  No TLS Verify: On
  → Traefik router  Host(`claude-mockups.holy-grail.ch`)
       middlewares: default-rate-limit → secure-headers   (TLS terminates here)
  → http://claude-mockups:80  (the Caddy container, on the traefik_proxy network)
       Caddy enforces basic auth, then serves:
  → /srv  ==  ./www
```

Files that make this work:

| File | Purpose |
|---|---|
| `docker-compose.yaml` | the Caddy container; injects the auth env vars |
| `Caddyfile` | serves `/srv` with directory browse + basic auth |
| `.env` | `BASIC_AUTH_USER` + bcrypt `BASIC_AUTH_HASH` (gitignored) |
| `set-password.sh` | interactively set the password (no plaintext in history) |
| `www/` | demo content, one subfolder per mockup (gitignored) |
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
2. **Basic-auth login** is set in `.env` (`BASIC_AUTH_USER` + bcrypt
   `BASIC_AUTH_HASH`). The hash never stores plaintext.

   **Change the password (interactive, never touches shell history):**
   ```bash
   ./set-password.sh
   ```
   It prompts silently, hashes via `caddy hash-password` (password read from
   stdin, never an argument), writes the `$$`-escaped hash into `.env`, and
   recreates the container.

   Manual equivalent, if you prefer:
   ```bash
   read -rsp "New password: " PW && echo
   printf '%s\n' "$PW" | docker run --rm -i caddy:alpine caddy hash-password | sed 's/\$/$$/g'
   unset PW   # paste the printed hash as BASIC_AUTH_HASH in .env, then: docker compose up -d --force-recreate
   ```

## Security notes

- Whole subdomain is gated by **basic auth** (shared login), enforced by Caddy;
  credentials live in `.env` as a **bcrypt hash** (no plaintext, gitignored).
- Secure headers (HSTS, nosniff, frameDeny, referrer-policy) are applied by
  Traefik, but **no strict CSP** — mockups legitimately use CDNs and inline
  scripts/styles.
- The container serves the `www` volume **read-only** and runs with
  `no-new-privileges`. No server-side code, just static files.
