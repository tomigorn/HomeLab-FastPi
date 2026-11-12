# Activity customizations (Docker/CUSTOMIZATIONS.md "Activity").
if want activity; then
  check activity.health '^healthy$' "$(docker inspect -f '{{.State.Health.Status}}' activity 2>&1)"
  check activity.hardening '^65060:65060 ro=true caps=\[ALL\] nnp mem=33554432$' "$(docker inspect -f '{{.Config.User}} ro={{.HostConfig.ReadonlyRootfs}} caps={{.HostConfig.CapDrop}} {{range .HostConfig.SecurityOpt}}{{if eq . "no-new-privileges:true"}}nnp{{end}}{{end}} mem={{.HostConfig.Memory}}' activity 2>&1)"
  # never served without a login: 302 to the SSO (Authentik application Activity)
  check activity.page-sso '^302 https://sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{http_code} %{redirect_url}' --resolve activity.holy-grail.ch:443:192.168.1.2 https://activity.holy-grail.ch/ | cut -c1-60)"
  # polls only while viewed: the first /api/state after idle waits for one immediate poll (max 4 s), so these reads count as a viewer for 2 min
  check activity.viewer-gated '^activity_viewer_active [01]$' "$(docker exec prometheus wget -qO- -T 5 http://activity:8080/metrics 2>&1 | grep '^activity_viewer_active ')"
  check activity.api '^"beefy":"(up|asleep|unknown)"$' "$(docker exec traefik wget -qO- -T 5 http://activity:8080/api/state 2>&1 | grep -o '"beefy":"[a-z]*"')"
  # only Traefik's pinned address may read the page and the state: another container on traefik_proxy gets 403
  check activity.traefik-only '^403,403$' "$(st() { docker exec server-specs wget -qO /dev/null -T 5 "http://activity:8080$1" 2>&1 | grep -o 'HTTP/1.1 [0-9]*' | cut -d' ' -f2 || true; }; echo "$(st /api/state),$(st /)")"
  # Traefik's internal routes (../Traefik/traefik/dynamic/activity-internal.yml): the Waker answers through it, qBittorrent too, and nobody but activity gets in
  check activity.waker-route '^"beefy":"(up|asleep)"$' "$(docker exec traefik wget -qO- -T 5 http://activity:8080/api/state 2>&1 | grep -o '"beefy":"[a-z]*"')"
  check activity.qbit-route '^"audiobook_downloads":\{"downloading":[0-9]+' "$(docker exec traefik wget -qO- -T 5 http://activity:8080/api/state 2>&1 | grep -oE '"audiobook_downloads":(null|\{"downloading":[0-9]+)')"
  check activity.internal-only '^403,403,403$' "$(st() { docker exec server-specs wget -qO /dev/null -T 5 "http://traefik:8080$1" 2>&1 | grep -o 'HTTP/1.1 [0-9]*' | cut -d' ' -f2 || true; }; echo "$(st /activity/waker/status),$(st /activity/gate/seerr/night-waiting.json),$(st '/activity/qbit/api/v2/torrents/info?category=abr')")"
  # Traefik never holds an idle connection to the beefy gate and never health-checks it (activity-internal.yml)
  check activity.gate-transport '^transport=activity-gate-no-idle idle=1s healthcheck=none$' "$(f="$DIR/../../Traefik/traefik/dynamic/activity-internal.yml"; gate=$(sed -n '/^  services:/,$p' "$f" | sed -n '/^    activity-gate:$/,/^    activity-qbit:$/p'); echo "transport=$(sed -n 's/^ *serversTransport: *//p' <<<"$gate") idle=$(sed -n '/^    activity-gate-no-idle:$/,/^    [a-z]/s/^ *idleConnTimeout: *//p' "$f") healthcheck=$(grep -q healthCheck <<<"$gate" && echo set || echo none)")"
  check activity.metrics-scraped '^1$' "$(docker exec prometheus wget -qO- -T 5 'http://localhost:9090/api/v1/query?query=up%7Bjob%3D%22activity%22%7D' 2>&1 | grep -o '"value":\[[^]]*\]' | grep -o '"[01]"' | tr -d '"')"
fi
