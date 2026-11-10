# Stonks customizations (Docker/CUSTOMIZATIONS.md "Stonks"): the self-built Rust service on scratch.
if want stonks; then
  IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' stonks 2>/dev/null)
  check stonks.rust '^\[/stonks\] 65007:65007 true$' "$(docker inspect -f '{{.Config.Entrypoint}} {{.Config.User}} {{.HostConfig.ReadonlyRootfs}}' stonks 2>&1)"
  check stonks.healthz '^\{"status":"ok"\}$' "$(curl -s -m 5 "http://$IP:8000/healthz")"
  check stonks.login-page '^200$' "$(curl -s -m 5 -o /dev/null -w '%{http_code}' "http://$IP:8000/login")"
  check stonks.auth-redirect '^303 /login$' "$(curl -s -m 5 -o /dev/null -w '%{http_code} %{redirect_url}' "http://$IP:8000/holdings" | sed "s#http://$IP:8000##")"
  # the price poll keeps writing: newest quote younger than three poll intervals (markets closed still refresh the cache)
  check stonks.prices-fresh '^fresh' "$(f=$(sqlite3 -readonly "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../Stonks" && pwd)/data/stonks.db" "select max(fetched_at) from price_cache" 2>/dev/null); age=$(( $(date +%s) - $(date -d "${f:-1970-01-01}" +%s 2>/dev/null || echo 0) )); [[ $age -lt 1800 ]] && echo "fresh ${age}s" || echo "stale ${age}s")"
fi
