# Stonks — deployment

Runtime deployment of the **Stonks** portfolio tracker. The application source lives in
`~/Documents/development/Stonks`; since 2026-11-10 the image is the Rust service in its `rust/`
folder (16 MB on `scratch`, a few MB RAM). The previous Python image stays as `stonks:pre-rust-2026-11-10`.

## Run
1. `cp .env.example .env` and fill in the non-secret values.
   Secrets go in `secrets/stonks.env` (owner `65007`, mode `0400`, mounted as `/app/.env`): `TELEGRAM_BOT_TOKEN`, `APP_PASSWORD_HASH`, `SESSION_SECRET`, single-quoted, `$` not doubled. Format: `.env.example`.
   Hash: `echo -n 'pw' | docker compose run --rm -T --no-deps stonks hashpw` (hashes from the old `hashpw.py` keep working).
2. Build and deploy: `./redeploy.sh` (DB copy to `data/backups/`, serialized two-job build under `~/.cache/claude-work/rust-build.lock`, `up -d`, `/healthz`).
   By hand: `cd ~/Documents/development/Stonks/rust && docker build --build-arg CARGO_BUILD_JOBS=2 -t stonks:latest .`, then `docker compose up -d`.

Weekly rebuild (Sat, fresh base, unit + black-box tests, rollback): `rebuild-local`, `Server/4-Security-Monitoring/auto-updates.md` "Local builds".

Tests before a redeploy (sandboxed, no network): in the code repo `docker build --target test rust/` (33 unit tests) and `tests/blackbox/run-rust.sh` (45 HTTP checks against the exported binary, `docker build --target export --output type=local,dest=rust/dist rust/` first).

Post-update check: `Docker/_global/scripts/post-update-check.sh Stonks` (image shape, healthz, login redirect, price cache fresh).

Rollback: `docker tag stonks:pre-rust-2026-11-10 stonks:latest && docker compose up -d` (data in `./data` is untouched, the schema is the same; a DB copy is in `./data/backups/`).

Data persists in `./data/stonks.db` (gitignored). Routing is handled by Traefik (`stonks.holy-grail.ch`, LAN/VPN only).
