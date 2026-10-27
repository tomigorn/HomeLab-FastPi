# Server-Specs customizations (Docker/CUSTOMIZATIONS.md "Server-Specs").
if want server-specs; then
  check specs.caddyfile '^Valid configuration$' "$(docker exec server-specs caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | grep -o 'Valid configuration' | head -1)"
  check specs.page '^200 [1-9][0-9]*$' "$(docker exec server-specs sh -c 'wget -qO /tmp/i -T 5 http://127.0.0.1/ && echo 200 $(wc -c < /tmp/i)' 2>&1 | tail -1)"
fi
