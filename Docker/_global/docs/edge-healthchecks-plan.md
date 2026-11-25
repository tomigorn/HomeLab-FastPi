# Edge healthchecks (FB-19): prepared, attended

Traefik and CrowdSec have no healthcheck; a hung one shows "Up". Adding one recreates the container (Traefik also needs a static-config change), so both are yes-first. Policy exceptions stay until applied (`Docker/_global/policy-exceptions.toml`).

| Container | Probe | Checked live 2026-11-25 |
|---|---|---|
| traefik | `traefik healthcheck` (reads `/etc/traefik/traefik.yml`, calls `/ping` on the `internal` entrypoint :8080) | needs `ping` in `traefik.yml` (not set yet) |
| crowdsec | `cscli lapi status` | `docker exec crowdsec cscli lapi status` → "You can successfully interact with Local API (LAPI)" |

## Traefik
1. `Docker/Traefik/traefik/traefik.yml`, top level:
   ```yaml
   ping:
     entryPoint: internal
   ```
2. `Docker/Traefik/docker-compose.yaml`, service `traefik`:
   ```yaml
   healthcheck:
     test: ["CMD", "traefik", "healthcheck"]
     interval: 30s
     timeout: 5s
     retries: 3
     start_period: 20s
   ```
3. Static config changes need a Traefik restart: apply step 1 and 2 together in one recreate. Before relying on it: `docker exec traefik traefik healthcheck` → `OK: http://:8080/ping`.
4. Apply: `SERVICES=traefik Docker/_global/scripts/update-project.sh Docker/Traefik recreate`, then `docker logs traefik --since 2m 2>&1 | grep -i error` (empty) and `docker inspect traefik -f '{{.State.Health.Status}}'` → healthy.
5. Rollback: revert both files, recreate the same way.

## CrowdSec
1. `Docker/CrowdSec/docker-compose.yaml`, service `crowdsec`:
   ```yaml
   healthcheck:
     test: ["CMD", "cscli", "lapi", "status"]
     interval: 60s
     timeout: 10s
     retries: 3
     start_period: 60s
   ```
2. Apply: `SERVICES=crowdsec Docker/_global/scripts/update-project.sh Docker/CrowdSec recreate`; check `docker inspect crowdsec -f '{{.State.Health.Status}}'` → healthy and the bouncer still answers (`docker logs traefik --since 2m 2>&1 | grep -i crowdsec`).
3. Rollback: revert, recreate.

After both: remove their `healthcheck` exceptions, `python3 Docker/_global/scripts/policy_check.py` → 0 violations.
