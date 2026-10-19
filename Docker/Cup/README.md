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
- Agents are only read when Cup refreshes (container start, Sundays 04:00, the refresh button). A host asleep at that moment is left out until the next refresh: `docker logs Cup` shows `Failed to refresh server`, and `cup_updates_*` count only the hosts that answered.
- An agent lists only images with a registry digest. Images put on a host with `docker load` have none and are missing from Cup until they are pulled once.

## Check

```bash
curl -s http://172.24.0.1:8000/api/v3/json | python3 -c 'import json,sys,collections; print(collections.Counter(i["server"] for i in json.load(sys.stdin)["images"]))'
```
