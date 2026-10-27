# cloudflared customizations (Docker/CUSTOMIZATIONS.md "cloudflared").
if want cloudflared; then
  check cf.pin '^cloudflare/cloudflared:[0-9]{4}\.[0-9]+\.[0-9]+$' "$(docker inspect -f '{{.Config.Image}}' cloudflared)"
  check cf.no-autoupdate-metrics '--no-autoupdate --metrics 0\.0\.0\.0:20241' "$(docker inspect -f '{{join .Config.Cmd " "}}' cloudflared)"
  check cf.tunnel-connections '^[1-9]' "$(docker exec prometheus wget -qO- -T 5 http://cloudflared:20241/metrics 2>/dev/null | awk '/^cloudflared_tunnel_ha_connections /{print $2}')"
  check cf.host-guard-range '^172\.20\.' "$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' cloudflared)"
  check cf.public-path '^200$' "$(curl -s -m 10 -o /dev/null -w '%{http_code}' --resolve home.holy-grail.ch:443:$(dig +short @1.1.1.1 home.holy-grail.ch | head -1) https://home.holy-grail.ch/)"
fi
