# Wiki customizations (Docker/CUSTOMIZATIONS.md "Wiki").
if want wiki; then
  check wiki.caddyfile '^Valid configuration$' "$(docker exec wiki caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | grep -o 'Valid configuration' | head -1)"
  check wiki.site '^200 [1-9][0-9]*$' "$(docker exec wiki sh -c 'wget -qO /tmp/i -T 5 http://127.0.0.1/ && echo 200 $(wc -c < /tmp/i)' 2>&1 | tail -1)"
  check wiki.not-found '^1$' "$(docker exec wiki wget -qO /dev/null -T 5 http://127.0.0.1/no-such-page 2>&1 | grep -c '404')"
fi
