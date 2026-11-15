# WG-Chores-Demo

Public demo of WG Chores, `https://wg-chores-demo.holy-grail.ch` (local accounts, no registration, no SSO). Same image as `../WG-Chores-v2`. Hosts the privacy policy and account-deletion page for the Play Store.

| What | Detail |
|---|---|
| Account | `reviewer`, password in `secrets/demo_password` (65035:65037 0400, 12+ characters) |
| Reset | every night 03:17 by `wg-chores-demo-reset.timer` (units in `systemd/`), by hand `docker exec wg-chores-demo /wg-chores demo-reset` |
| Route | `../Traefik/traefik/dynamic/wg-chores-v2.yml` router `wg-chores-demo` |
| Update | `auto-update.conf` row `auto` |
| Check | `../_global/scripts/post-update-check.sh WG-Chores-Demo` |
