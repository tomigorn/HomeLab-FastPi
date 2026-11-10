# Claude-Mockups customizations (Docker/CUSTOMIZATIONS.md "Claude-Mockups").
if want claude-mockups answer-inbox; then
  check mockups.caddyfile '^Valid configuration$' "$(docker exec claude-mockups caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | grep -o 'Valid configuration' | head -1)"
  check mockups.assets '^ok$' "$(docker exec claude-mockups wget -qO /dev/null -T 5 http://127.0.0.1/_assets/answer.js && docker exec claude-mockups wget -qO /dev/null -T 5 http://127.0.0.1/_assets/answer.css && echo ok)"
  check mockups.answer-inbox '^ok$' "$(docker exec claude-mockups wget -qO /dev/null -T 5 http://127.0.0.1/_inbox/health && echo ok)"
  # a fresh nonce as the choice proves this run's submit landed; the answer file is owned by the inbox uid and simply overwritten next run
  check mockups.answer-roundtrip '^ok$' "$(t=post-update-check; n=$(date +%s%N); f=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../Claude-Mockups" && pwd)/answers/$t.json; docker exec claude-mockups wget -qO /dev/null -T 5 --header 'Content-Type: application/json' --post-data "{\"token\":\"$t\",\"choice\":\"$n\"}" http://127.0.0.1/_inbox/submit && python3 -c 'import json,sys; print("ok" if json.load(open(sys.argv[1]))["choice"] == sys.argv[2] else "wrong")' "$f" "$n" 2>&1 | tail -1)"
  # Caddy answers only Traefik (172.24.255.3) and its own loopback (the checks above): another container on traefik_proxy gets 403 for the inbox and the demos
  check mockups.inbox-traefik-only '^traefik=ok other=403,403$' "$(st() { docker exec server-specs wget -qO /dev/null -T 5 "http://claude-mockups$1" 2>&1 | grep -o 'HTTP/1.1 [0-9]*' | cut -d' ' -f2 || true; }; echo "traefik=$(docker exec traefik wget -qO /dev/null -T 5 http://claude-mockups/_inbox/health && echo ok) other=$(st /_inbox/health),$(st /)")"
  check mockups.forward-auth '^https://sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve claude-mockups.holy-grail.ch:443:192.168.1.2 https://claude-mockups.holy-grail.ch/ | cut -c1-60)"
fi
