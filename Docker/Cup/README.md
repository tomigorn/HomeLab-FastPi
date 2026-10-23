# Cup

Image update checker, web UI at `https://cup.holy-grail.ch` (Holy Grail login). Fetch-only, never updates anything. Config: `cup.json`.

## Servers

Cup reads no socket itself (`"socket": "none"`); every host, fastpi included, is an agent in `cup.json` → `servers`, so the UI names them fastpi, beefy, tower.

| Server | URL | Agent lives in | Started by |
|---|---|---|---|
| fastpi | `http://cup-agent-fastpi:8000` (compose network `cup_agents`) | `Docker/Cup`, service `cup-agent-fastpi`, `cup-agent.json` | `docker compose up -d` |
| beefy | `http://192.168.1.102:8000` | beefy repo, `Docker/Cup-Agent/` | `docker compose up -d` |
| tower | `http://192.168.1.101:8000` | tower repo, `boot/config/scripts/stacks/cup-agent/` | `up.sh`, then Docker restarts it at array start |

- Agents have no auth: each host allows port `8000` only from `192.168.1.2` (`DOCKER-USER` rule).
- After editing `cup.json`: `docker restart Cup`.
- Startup race: Cup's own startup refresh runs before the agent answers, so the one-shot `cup-refresh` (curl, uid 65023, exits when done) waits for the agent and Cup, then calls `/api/v3/refresh` once. Data is there ~1 min after `docker compose up -d`. A sleeping beefy only makes that refresh slower (3 retries, then it is left out until the next refresh). Cup's image is distroless, so no healthcheck / `service_healthy`.
- Agents are only read when Cup refreshes (container start, Sundays 04:00, the refresh button). A host asleep at that moment is left out until the next refresh: `docker logs Cup` shows `Failed to refresh server`, and `cup_updates_*` count only the hosts that answered.
- An agent lists only images with a registry digest. Images put on a host with `docker load` have none and are missing from Cup until they are pulled once.

## Locally built images

An image built here (`build:` in compose) has no registry copy, so Cup cannot track it. Its base image is listed in `images.extra` of the agent config (`cup-agent.json` on fastpi, `Docker/Cup-Agent/cup.json` on beefy) instead, so a new base shows up as an update. An `extra` entry must be a versioned tag or already on the host (`alpine:latest` is not accepted if not pulled: the agent crash-loops). On beefy the local images are in `images.exclude`, which stops their "Unauthorized" errors; fastpi's have no digest and never appear.

| Host | Local image | Base (tracked) | Rebuild |
|---|---|---|---|
| fastpi | languagetool-local | `erikvl87/languagetool:6.8` | `Docker/LanguageTool/README.md` |
| fastpi | clamav-local, virustotal-local | `alpine:latest`, `python:3.12-alpine` | `Docker/antivirus/README.md` |
| fastpi | m4b-auto-merge, beefy-waker, tower-waker, avatar-picker | `python:3.12/3.13-alpine` | their READMEs, `Rebuild` |
| beefy | jellyfin-local, clamav-local, ryot-go | `lscr.io/linuxserver/jellyfin`, `alpine:latest`, `python:3.13-alpine` | their READMEs, `Rebuild` |

CVEs: the weekly Trivy image scan scans fastpi's local images directly and, for beefy's, the registry copy of each Dockerfile `FROM` (`Server/4-Security-Monitoring/README.md`).

After editing a config: `docker restart cup-agent-fastpi Cup` (fastpi) or `docker restart cup-agent` (beefy).

## Check

```bash
curl -s http://172.24.0.1:8000/api/v3/json | python3 -c 'import json,sys,collections; print(collections.Counter(i["server"] for i in json.load(sys.stdin)["images"]))'
```
