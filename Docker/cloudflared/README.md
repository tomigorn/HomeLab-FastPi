# cloudflared

Cloudflare Tunnel (`terminal`/web routes are managed in the Cloudflare dashboard). Token in `secrets/tunnel_token.secret`.

| What | How |
|---|---|
| Image | pinned `cloudflare/cloudflared:2026.10.5` |
| Bump | read the [release notes](https://github.com/cloudflare/cloudflared/releases), edit the tag in `docker-compose.yaml`, `docker compose up -d` (tunnel bounces for seconds, owner approval) |
| Metrics | `--metrics 0.0.0.0:20241`, not published; Prometheus scrapes `cloudflared:20241` over `infra__cloudflare_default` |
| Alert | `CloudflaredTunnelDown` (see `grafana/README.md`) |
| Check | `docker exec cloudflared cloudflared tunnel --metrics localhost:20241 ready` |
