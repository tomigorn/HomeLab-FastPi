# Tech-Radar customizations (Docker/CUSTOMIZATIONS.md "Tech-Radar").
if want tech-radar; then
  check radar.health '^healthy$' "$(docker inspect -f '{{.State.Health.Status}}' tech-radar 2>&1)"
  check radar.hardening '^65061:65061 ro=true caps=\[ALL\] nnp mem=33554432$' "$(docker inspect -f '{{.Config.User}} ro={{.HostConfig.ReadonlyRootfs}} caps={{.HostConfig.CapDrop}} {{range .HostConfig.SecurityOpt}}{{if eq . "no-new-privileges:true"}}nnp{{end}}{{end}} mem={{.HostConfig.Memory}}' tech-radar 2>&1)"
  check radar.index '^200$' "$(docker exec traefik wget -S -qO /dev/null -T 5 http://tech-radar/ 2>&1 | grep -o 'HTTP/1.1 [0-9]*' | tail -1 | cut -d' ' -f2)"
  # item page by directory URL (no .html): the Caddy try_files rule
  check radar.item-page '^200$' "$(docker exec traefik wget -S -qO /dev/null -T 5 http://tech-radar/hardware/fastpi/ 2>&1 | grep -o 'HTTP/1.1 [0-9]*' | tail -1 | cut -d' ' -f2)"
  # never served without a login: 302 to the SSO (Authentik application Tech Stack)
  check radar.page-sso '^302 https://sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{http_code} %{redirect_url}' --resolve stack.holy-grail.ch:443:192.168.1.2 https://stack.holy-grail.ch/ | cut -c1-60)"
  check radar.csp '^script-self$' "$(grep -q "script-src 'self';" "$DIR/../../Traefik/traefik/dynamic/tech-radar.yml" && ! grep -q "script-src[^;]*unsafe" "$DIR/../../Traefik/traefik/dynamic/tech-radar.yml" && echo script-self || echo weak)"
fi
