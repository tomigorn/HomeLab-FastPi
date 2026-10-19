# HomeLab-FastPi
Everything that runs on fastpi: Docker stacks under `Docker/`, server docs under `Server/`, scripts. The repo is public: no secrets, no mail addresses, no real names.

## Git commits
- `Project Name: short description`. The project is the folder or service changed, written as it is normally written: `Traefik: add Dashy route`, `WireguardVPN: remove old network`, `Global: smoke-test …` for `Docker/_global`. Several projects: `Traefik, Authentik: …`.

## Docker projects (`Docker/`)
- One folder per project, named as normally written (PascalCase, `Portainer-Agent`). `COMPOSE_PROJECT_NAME` in `.env` is that name in lowercase (Compose rejects uppercase).
- The sample files in `Docker/` are the template. Every project has these four files:
  - `docker-compose.yaml`: the sectioned layout with banner blocks for Services, Networks, Volumes and a `# NAME` banner above each service.
  - `.env.example`: identical to `.env` except secret values are blank (passwords, tokens, hashes, API keys). Same variables, order and comments, non-secret values verbatim. Starts with `COMPOSE_PROJECT_NAME=`.
  - `.env`: the real values, gitignored.
  - `.gitignore`: ignores `.env` and every sensitive file or folder, per the sample.
- Traefik config lives in `Docker/Traefik/traefik/dynamic/` and hot-reloads; Traefik fails closed, so check `docker logs traefik` after every change. `local-networks@file` is the single definition of "home + VPN"; `authentik@file` is the login gate.
- After changes: `Docker/_global/scripts/smoke-test.sh` must stay green.

## Project review checklist (`Docker/_global/checklist.md`)
- Columns: `Project | Reviewed | Deployed | Image / Tag Version | my update performed date | Tag`.
- A new project gets a row with `❌` in Reviewed and Deployed and the other columns empty.
- Never set a `✅` and never fill the version, date or tag columns on your own; only when I say so.
