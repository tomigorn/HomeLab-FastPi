# Miniflux customizations (Docker/CUSTOMIZATIONS.md "Miniflux").
if want miniflux miniflux-db; then
  check mf.health '^miniflux=healthy miniflux-db=healthy$' "$(for c in miniflux miniflux-db; do printf '%s=%s ' "$c" "$(docker inspect -f '{{.State.Health.Status}}' "$c" 2>&1)"; done | sed 's/ $//')"
  check mf.hardening '^65066:65066 ro=true caps=\[ALL\] nnp$' "$(docker inspect -f '{{.Config.User}} ro={{.HostConfig.ReadonlyRootfs}} caps={{.HostConfig.CapDrop}} {{range .HostConfig.SecurityOpt}}{{if eq . "no-new-privileges:true"}}nnp{{end}}{{end}}' miniflux 2>&1)"
fi
if want miniflux; then
  mf_api() { curl -s -m 20 -H "X-Auth-Token: $(cat /home/pi/Projects/Docker/Miniflux/secrets/api_key 2>/dev/null)" "http://127.0.0.1:8097/v1$1"; }
  # only the two filtered feeds (vl-severity-feed over vl_feeds, CVSS >= 7.0), none failing
  check mf.feeds '^2 feeds, 0 failing, watchlist kev$' "$(mf_api /feeds | python3 -c 'import json,sys; fs=json.load(sys.stdin); u={f["feed_url"] for f in fs}; print(len(fs), "feeds,", sum(1 for f in fs if f["parsing_error_count"]), "failing,", "watchlist" if "http://vl-severity-feed:8080/watchlist.atom" in u else "-", "kev" if "http://vl-severity-feed:8080/kev.atom" in u else "-")' 2>&1)"
  # Releases dropped (owner 2026-11-16): no user keeps an unfiltered feed or the category
  check mf.no-unfiltered '^0 0$' "$(docker exec miniflux-db psql -U miniflux -d miniflux -Atc "select (select count(*) from feeds where feed_url not like 'http://vl-severity-feed:8080/%'), (select count(*) from categories where title = 'Releases')" 2>&1 | tr '|' ' ')"
  check mf.telegram '^t t$' "$(docker exec miniflux-db psql -U miniflux -d miniflux -Atc "select telegram_bot_enabled, telegram_bot_token <> '' from integrations where user_id = 1" 2>&1 | tr '|' ' ')"
  check mf.page-sso '^302 https://sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{http_code} %{redirect_url}' --resolve news.holy-grail.ch:443:192.168.1.2 https://news.holy-grail.ch/ | cut -c1-60)"
  # the login header counts only from Traefik's pinned address: another container on traefik_proxy lands on the sign-in page
  check mf.proxy-auth-traefik-only '^Sign In' "$(docker exec server-specs wget -qO- -T 10 --header 'X-authentik-username: nobody-real' http://miniflux:8080/unread 2>&1 | grep -o '<title>[^<]*' | head -1 | cut -c8-)"
  # user creation is on: the refused header must not leave an account behind
  check mf.no-forged-user '^0$' "$(docker exec miniflux-db psql -U miniflux -d miniflux -Atc "select count(*) from users where username = 'nobody-real'" 2>&1)"
  # only the admin sends to the alert chat (users created on first visit get no copy of the integration)
  check mf.telegram-admin-only '^0$' "$(docker exec miniflux-db psql -U miniflux -d miniflux -Atc "select count(*) from integrations i, integrations a where a.user_id = 1 and i.user_id <> 1 and i.telegram_bot_enabled and i.telegram_bot_token = a.telegram_bot_token" 2>&1)"
  check mf.user-sync '^active success$' "$(systemctl is-active miniflux-feed-sync.timer 2>&1) $(systemctl show -p Result --value miniflux-feed-sync.service 2>&1)"
fi
