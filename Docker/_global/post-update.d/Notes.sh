# Notes customizations (Docker/CUSTOMIZATIONS.md "Notes").
if want notes; then
  check notes.caddyfile '^Valid configuration$' "$(docker exec notes caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | grep -o 'Valid configuration' | head -1)"
  check notes.site '^200 [1-9][0-9]*$' "$(docker exec notes sh -c 'wget -qO /tmp/i -T 5 http://127.0.0.1/ && echo 200 $(wc -c < /tmp/i)' 2>&1 | tail -1)"
  check notes.forward-auth 'sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve notes.holy-grail.ch:443:192.168.1.2 https://notes.holy-grail.ch/ | cut -c1-60)"
fi
