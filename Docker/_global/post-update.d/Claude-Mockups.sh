# Claude-Mockups customizations (Docker/CUSTOMIZATIONS.md "Claude-Mockups").
if want claude-mockups answer-inbox; then
  check mockups.caddyfile '^Valid configuration$' "$(docker exec claude-mockups caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | grep -o 'Valid configuration' | head -1)"
  check mockups.assets '^ok$' "$(docker exec claude-mockups wget -qO /dev/null -T 5 http://127.0.0.1/_assets/answer.js && docker exec claude-mockups wget -qO /dev/null -T 5 http://127.0.0.1/_assets/answer.css && echo ok)"
  check mockups.answer-inbox '^ok$' "$(docker exec claude-mockups wget -qO /dev/null -T 5 http://127.0.0.1/_inbox/health && echo ok)"
  check mockups.forward-auth '^https://sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve claude-mockups.holy-grail.ch:443:192.168.1.2 https://claude-mockups.holy-grail.ch/ | cut -c1-60)"
fi
