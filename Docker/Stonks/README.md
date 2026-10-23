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

Data persists in `./data/stonks.db` (gitignored). Routing is handled by Traefik
(`stonks.holy-grail.ch`).
