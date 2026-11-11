# Activity customizations (Docker/CUSTOMIZATIONS.md "Activity").
if want activity; then
  check activity.health '^healthy$' "$(docker inspect -f '{{.State.Health.Status}}' activity 2>&1)"
  check activity.hardening '^65060:65060 ro=true caps=\[ALL\] nnp mem=33554432$' "$(docker inspect -f '{{.Config.User}} ro={{.HostConfig.ReadonlyRootfs}} caps={{.HostConfig.CapDrop}} {{range .HostConfig.SecurityOpt}}{{if eq . "no-new-privileges:true"}}nnp{{end}}{{end}} mem={{.HostConfig.Memory}}' activity 2>&1)"
  # never served without a login: 302 to the SSO once the Authentik application exists, an error from the outpost before that
  check activity.page-sso '^(302 https://sso\.holy-grail\.ch/application/o/authorize/|4[0-9][0-9] |5[0-9][0-9] )' "$(curl -sk -m 10 -o /dev/null -w '%{http_code} %{redirect_url}' --resolve activity.holy-grail.ch:443:192.168.1.2 https://activity.holy-grail.ch/ | cut -c1-60)"
  check activity.api '^"beefy":"(up|asleep|unknown)"$' "$(docker exec traefik wget -qO- -T 5 http://activity:8080/api/state 2>&1 | grep -o '"beefy":"[a-z]*"')"
  # only Traefik's pinned address may read the page and the state: another container on traefik_proxy gets 403
  check activity.traefik-only '^403,403$' "$(st() { docker exec server-specs wget -qO /dev/null -T 5 "http://activity:8080$1" 2>&1 | grep -o 'HTTP/1.1 [0-9]*' | cut -d' ' -f2 || true; }; echo "$(st /api/state),$(st /)")"
  check activity.metrics-scraped '^1$' "$(docker exec prometheus wget -qO- -T 5 'http://localhost:9090/api/v1/query?query=up%7Bjob%3D%22activity%22%7D' 2>&1 | grep -o '"value":\[[^]]*\]' | grep -o '"[01]"' | tr -d '"')"
fi
