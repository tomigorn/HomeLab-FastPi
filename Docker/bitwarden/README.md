# Vaultwarden (bitwarden) — DEPRECATED / NOT DEPLOYED

**Status: decommissioned 2026-10-18** (user decision). The container was removed;
this project is kept as a starting point for a possible future redeploy.

- Data backup (encrypted vault DB, attachments, keys):
  `~/backups/decommissioned/vaultwarden-data-2026-10-18.tgz` on fastpi (mode 600).
  The live `./data` directory was left in place (gitignored).
- It had 1 user (tsmil@live.com), no organisations, no 2FA, sign-ups off.
- Routing was via Traefik Docker labels (`BITWARDEN_DOMAIN`, Let's Encrypt
  resolver `le`); removing the container removed the route. If a DDNS hostname
  still points here, it can be dropped.

To redeploy: review the image tag (pin it), enable 2FA / SSO, then
`docker compose up -d` and move it to the shared `local-networks` / Authentik setup.
