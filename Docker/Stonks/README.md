# Stonks — deployment

Runtime deployment of the **Stonks** portfolio tracker. The application source
lives in the development repo at `~/Documents/development/Stonks`, which builds
the `stonks:latest` image this compose runs.

## Run
1. `cp .env.example .env` and fill in the non-secret values.
   Secrets go in `secrets/stonks.env` (owner `65007`, mode `0400`, mounted as `/app/.env`): `TELEGRAM_BOT_TOKEN`, `APP_PASSWORD_HASH`, `SESSION_SECRET`, single-quoted, `$` not doubled. Format: `.env.example`.
2. Build/refresh the image from the code repo:
   `cd ~/Documents/development/Stonks && docker build -t stonks:latest .`
3. `docker compose up -d`

Weekly rebuild (Sat, fresh base, the code repo's tests in the new image, rollback): `rebuild-local`, `Server/4-Security-Monitoring/auto-updates.md` "Local builds".

Tests before a redeploy (sandboxed, no network): `~/Documents/development/Stonks/tests/run-unit.sh` and `tests/blackbox/run.sh stonks:latest` (45 HTTP checks against the image).

Rollback: `docker tag stonks:pre-<date> stonks:latest && docker compose up -d` (the previous image is tagged `stonks:pre-<date>` before a redeploy; data in `./data` is untouched, a DB copy is in `./data/backups/`).

Data persists in `./data/stonks.db` (gitignored). Routing is handled by Traefik
(`stonks.holy-grail.ch`).
