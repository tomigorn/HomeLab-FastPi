# bitwarden — deploy prep (NOT deployed; intentionally stopped)

Status: **stopped on purpose** (user decision 2026-10-22). May never be redeployed. Do not auto-start it.

Container hardening already applied to the compose (takes effect whenever it is next started):
- `no-new-privileges: true`

If it is ever deployed again, two things must be done first (only then):
1. Set `BITWARDEN_DOMAIN=` in `.env` (the real public URL; it is referenced by the Traefik labels + the app).
2. Replace the plaintext `ADMIN_TOKEN` in `.env` with an Argon2 PHC hash:
   `docker run --rm -it vaultwarden/server /vaultwarden hash`
   then paste the result as `ADMIN_TOKEN=`, escaping every `$` as `$$` (compose interpolation).
   (Headless hashing is awkward here — the interactive `hash` command needs a TTY.)
3. Optional: the SMTP settings in the DB use the deprecated `smtp_ssl`; switch to `SMTP_SECURITY` via the admin UI.
