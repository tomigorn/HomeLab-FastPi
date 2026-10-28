# Traefik customizations (Docker/CUSTOMIZATIONS.md "Traefik"). Sourced by post-update-check.sh.
TR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../Traefik" && pwd)
tcode() { curl -sk -m 10 -o /dev/null -w '%{http_code}' "$@"; }
if want traefik; then
  check traefik.version-pin '^3\.7\.16$' "$(docker exec traefik traefik version 2>/dev/null | awk '/Version:/{print $2}')"
  check traefik.local-plugins 'crowdsec-bouncer.*realip' "$(docker logs traefik 2>&1 | grep 'Plugins loaded' | tail -1 | grep -o 'plugins=.*')"
  check traefik.config-reload '^[1-9]' "$(docker exec traefik wget -qO- -T 5 http://127.0.0.1:8080/metrics 2>/dev/null | awk '/^traefik_config_last_reload_success /{print $2}')"
  check traefik.authentik-ip '^10\.24\.15\.3$' "$(docker inspect -f '{{(index .NetworkSettings.Networks "traefik_authentik").IPAddress}}' traefik)"
  check traefik.forward-auth 'sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve traefik.holy-grail.ch:443:192.168.1.2 https://traefik.holy-grail.ch/dashboard/ | cut -c1-60)"
  check traefik.local-networks '403' "$(docker exec claude-mockups wget -q -S -T 8 --no-check-certificate --header 'Host: grafana.holy-grail.ch' -O /dev/null https://172.24.255.3/ 2>&1 | grep -m1 -o 'HTTP/[0-9.]* [0-9]*')"
  check traefik.real-ip '^real$' "$(ip=$(dig +short @1.1.1.1 sso.holy-grail.ch | head -1); curl -s -m 8 -o /dev/null --resolve "sso.holy-grail.ch:443:$ip" -H 'X-Forwarded-For: 203.0.113.77' https://sso.holy-grail.ch/-/health/live/; sleep 1
    r=$(docker logs --since 15s authentik-server 2>&1 | grep 'health/live' | grep -o '"remote":"[^"]*"' | tail -1 | cut -d'"' -f4)
    case $r in 203.0.113.77) echo spoofed ;; 172.*|10.*|192.168.*|"") echo "proxy ${r:-none}" ;; *) echo real ;; esac)"
  check traefik.crowdsec-bouncer '^403 200$' "$(tip=$(docker inspect traefik -f '{{(index .NetworkSettings.Networks "traefik_proxy").IPAddress}}')
    bip=$(docker exec crowdsec cscli decisions list -o json --origin CAPI 2>/dev/null | python3 -c 'import json,sys; print(next((d["value"] for a in json.load(sys.stdin) or [] for d in a["decisions"] if d["type"]=="ban" and d["scope"]=="Ip" and ":" not in d["value"] and "h" in d["duration"]), ""))')
    echo "$(tcode --resolve home.holy-grail.ch:443:$tip -H "Cf-Connecting-Ip: ${bip:-0.0.0.0}" https://home.holy-grail.ch/) $(tcode --resolve home.holy-grail.ch:443:$tip -H 'Cf-Connecting-Ip: 203.0.113.7' https://home.holy-grail.ch/)")"
  check traefik.bouncer-fail-open '^stream -1$' "$(awk '/crowdsecMode:/{m=$2} /updateMaxFailure:/{f=$2} END{print m, f}' "$TR/traefik/dynamic/crowdsec.yml")"
  check traefik.portainer-password-block '^403$' "$(tcode -X POST --resolve portainer.holy-grail.ch:443:192.168.1.2 -H 'Content-Type: application/json' --data '{}' https://portainer.holy-grail.ch/api/auth)"
  check traefik.jellyfin-password-block '^403 403$' "$(for p in /Users/AuthenticateByName /emby/Users/abc/Authenticate; do tcode -X POST --resolve jellyfin.holy-grail.ch:443:192.168.1.2 "https://jellyfin.holy-grail.ch$p"; echo; done | xargs)"
  check traefik.nextcloud-login-block '^403$' "$(tcode -X POST --resolve cloud.holy-grail.ch:443:192.168.1.2 https://cloud.holy-grail.ch/login)"
  check traefik.jellyfin-web-fresh '^(200|beefy asleep)$' "$(if nc -z -w2 192.168.1.102 22 >/dev/null 2>&1; then u=https://jellyfin.holy-grail.ch/web/main.jellyfin.bundle.js
    e=$(curl -sk -m 10 -o /dev/null -D - --resolve jellyfin.holy-grail.ch:443:192.168.1.2 "$u" | tr -d '\r' | awk 'tolower($1)=="etag:"{print $2}')
    tcode --resolve jellyfin.holy-grail.ch:443:192.168.1.2 -H "If-None-Match: $e" "$u"; else echo beefy asleep; fi)"
  check traefik.tracker-allow-list '^404 403$' "$(echo "$(tcode --resolve tracker.holy-grail.ch:443:192.168.1.2 https://tracker.holy-grail.ch/zz-no-such-route) $(tcode -X POST --resolve tracker.holy-grail.ch:443:192.168.1.2 https://tracker.holy-grail.ch/webhook/jellyfin/post-update)")"
  check traefik.tracker-encoded-block '^400 400 403$' "$(for p in /accounts/signup%2F /details/image%5Cx /accounts/signup%252F; do tcode --resolve tracker.holy-grail.ch:443:192.168.1.2 "https://tracker.holy-grail.ch$p"; echo; done | xargs)"
  check traefik.encoded-chars '^400 (200|404) 400$' "$(echo "$(tcode --resolve sso.holy-grail.ch:443:192.168.1.2 'https://sso.holy-grail.ch/a%2Fb') $(tcode --resolve sso.holy-grail.ch:443:192.168.1.2 'https://sso.holy-grail.ch/-/health/live/%23') $(tcode --resolve wg-aemtli.ddns.net:8443:127.0.0.1 'https://wg-aemtli.ddns.net:8443/a%3Fb')")"
  check traefik.lt-preflight '^404 200$' "$(echo "$(tcode -X OPTIONS --resolve lang-tool.ddns.net:8443:127.0.0.1 https://lang-tool.ddns.net:8443/v2/languages) $(tcode -X OPTIONS -H 'Origin: chrome-extension://check' -H 'Access-Control-Request-Method: POST' --resolve lang-tool.ddns.net:8443:127.0.0.1 https://lang-tool.ddns.net:8443/v2/check)")"
  check traefik.lt-token-routers '^[1-9][0-9]* routers, token 200, bare 404$' "$(f=$TR/traefik/dynamic/languagetool-token.yml
    n=$(grep -cE '^\s{4}languagetool-token-[^:]+:' "$f")
    t=$(python3 -c 'import re,sys; m=re.search(r"PathPrefix\(`(/[^`]+)`\)", open(sys.argv[1]).read()); print(m.group(1) if m else "/none")' "$f" | { read -r p; printf 'url = "https://lang-tool.ddns.net:8443%s/languages"\n' "$p" | curl -sk -m 10 -o /dev/null -w '%{http_code}' --resolve lang-tool.ddns.net:8443:127.0.0.1 -K -; })
    echo "$n routers, token $t, bare $(tcode --resolve lang-tool.ddns.net:8443:127.0.0.1 https://lang-tool.ddns.net:8443/v2/languages)")"
  check traefik.lt-token-quiet '^([0-9]+) routers \1 quiet 65026$' "$(f=$TR/traefik/dynamic/languagetool-token.yml; echo "$(grep -cP '^ {4}languagetool-token-(?!strip-)[^:]+:' "$f") routers $(grep -c 'accessLogs: false' "$f") quiet $(stat -c %g "$f")")"
  check traefik.requests-csp-report-only '^1$' "$(grep -c "contentSecurityPolicyReportOnly: \"default-src 'self'; script-src 'self';" "$TR/traefik/dynamic/requests.yml")"
  check traefik.metrics-internal '^000 1$' "$(echo "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://192.168.1.2:8080/metrics) $(docker exec prometheus wget -qO- -T 5 http://traefik:8080/metrics 2>/dev/null | grep -m1 -c traefik_entrypoint_requests_total)")"
  check traefik.logrotate '^same$' "$(cmp -s "$TR/logrotate/traefik" /etc/logrotate.d/traefik && echo same || echo differs)"
fi
