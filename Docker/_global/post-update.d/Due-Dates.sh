# Due-Dates customizations (Docker/CUSTOMIZATIONS.md "Due-Dates").
if want due-dates; then
  check due.caddyfile '^Valid configuration$' "$(docker exec due-dates caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | grep -o 'Valid configuration' | head -1)"
  check due.json '^200 items$' "$(docker exec due-dates sh -c 'wget -qO /tmp/d -T 5 http://127.0.0.1/due-dates.json && grep -q "\"items\"" /tmp/d && echo 200 items' 2>&1 | tail -1)"
fi
