# Stonks — deployment

Runtime deployment of the **Stonks** portfolio tracker. The application source
lives in the development repo at `~/Documents/development/Stonks`, which builds
the `stonks:latest` image this compose runs.

## Run
1. `cp .env.example .env` and fill in the values (Telegram token/chat id, app
   credentials, session secret — remember to double `$` to `$$` in
   `APP_PASSWORD_HASH`).
2. Build/refresh the image from the code repo:
   `cd ~/Documents/development/Stonks && docker build -t stonks:latest .`
3. `docker compose up -d`

Data persists in `./data/stonks.db` (gitignored). Routing is handled by Traefik
(`stonks.holy-grail.ch`).
