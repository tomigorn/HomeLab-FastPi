# WG-Chores-v2

WG Chores v2 for the WG, `https://wg-chores.holy-grail.ch` (SSO only, group WG). Code and owner guide: `~/Documents/development/WG-Chores` (`docs/guides/go-live-holy-grail.md`). The public demo is `../WG-Chores-Demo`.

| What | Detail |
|---|---|
| Image | `tomigorn/wg-chores:latest` (Docker Hub, built by the code repo's GitHub Actions); Cup lists it |
| Login | the app's own OIDC (`../Authentik/scripts/provision-wg-chores-sso.py`), no forward auth |
| Secret | `secrets/oidc_client_secret`, 65035:65037 0400, written by the provisioning |
| Data | volume `wg-chores-v2_wg-chores-v2-data` (`/data/wg-chores.db`, `vapid.key`, `secret.key`) |
| Route | `../Traefik/traefik/dynamic/wg-chores-v2.yml` |
| Update | `auto-update.conf` row `notify` (the app migrates its DB one way): Telegram names the command, it backs up the volume first |
| Check | `../_global/scripts/post-update-check.sh WG-Chores-v2` |

```
docker compose up -d
docker exec wg-chores-v2 /wg-chores backup /data/backup.db        # consistent copy while running
docker exec wg-chores-v2 /wg-chores revoke-sessions <username>     # after removing someone from WG
```
