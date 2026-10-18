# SSO-only, batch A: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** close every network-reachable username/password login on fastpi where Claude can do it
alone and low-risk. User requirement 2026-10-18: "disable local user login and only ever allow
authentik/holy grail sso login". Recovery when Authentik is down = server shell only.

**Input:** `docs/superpowers/specs/2026-10-19-sso-only-inventory.md` (per-app evidence).
This plan supersedes the "break-glass login" column of `2026-10-18-homelab-admin-sso-design.md`.

## Tasks
1. **Traefik dashboard:** delete router `dashboard`, middleware `dashboard-auth` and `dashboard.users`. Recovery note in the Authentik README.
2. **wg-easy:** `DISABLE_PASSWORD_AUTH=true` (the admin is already linked to Authentik). Remove `WG_EASY_ADMIN_PASSWORD`/`USERNAME` from `.env` and `.env.example` once nothing uses them. Verify `POST /api/auth/password` is refused.
3. **Grafana:** `GF_AUTH_DISABLE_LOGIN_FORM=true`, `GF_AUTH_BASIC_ENABLED=false`, port `127.0.0.1:3001:3000`. Recovery: flip the flag back plus an ssh tunnel, or `grafana cli admin reset-admin-password`.
4. **Portainer:** Traefik deny router for POST `^/api/+auth/?$` (keep `/api/auth/oauth/validate`), port `127.0.0.1:9443:9443`. Recovery: ssh tunnel.
5. **Localhost-only host ports:** InfluxDB 8086, Prometheus 9090, Alertmanager 9093, port-updater 8087, Mousehole 5010, fastpi qBittorrent 8085, fastpi SABnzbd 8090. Before each one, check every consumer: Grafana datasources, HA (127.0.0.1), the Telegraf target, beefy/tower scrapers, the homelab dashboard links. Cup 8000 only after re-pointing its Prometheus/json-exporter target to the docker network.
6. **AdGuard:** remove the `admin` user, leaving only `authentik-proxy`. Edit with the container stopped, keep the DNS outage under 1 s, and back up first.
7. **Docs + smoke test:** update `smoke-test.sh` checks that relied on break-glass logins or LAN ports. Update the READMEs and the Authentik README "Admin SSO" table, where the break-glass column becomes "shell recovery".

Batches B, C and D (AdGuard bind, Claude-Mockups forward auth, dev-app ports, HA providers, LoyaltyCards, Stonks, beefy firewall, Nextcloud, Unraid) need user decisions or awake hosts; they are tracked in the inventory.
