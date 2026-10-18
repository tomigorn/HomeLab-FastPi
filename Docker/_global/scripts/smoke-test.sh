#!/usr/bin/env bash
# Smoke test for everything updated in the 2026-10-17 rounds (and a general
# health check afterwards). Read-only; never wakes beefy or tower: they are only
# checked if already awake.   Usage: _global/scripts/smoke-test.sh
set -uo pipefail
PASS=0; FAIL=0; SKIP=0
ok()   { printf '  \e[32mPASS\e[0m %-34s %s\n' "$1" "${2:0:70}"; PASS=$((PASS+1)); }
bad()  { printf '  \e[31mFAIL\e[0m %-34s %s\n' "$1" "${2:-}"; FAIL=$((FAIL+1)); }
skip() { printf '  \e[33mSKIP\e[0m %-34s %s\n' "$1" "${2:-}"; SKIP=$((SKIP+1)); }
check() { # check <name> <expected-regex> <actual>
  if [[ $3 =~ $2 ]]; then ok "$1" "$3"; else bad "$1" "got: $3"; fi; }
running() { # running <container...>  -> running, healthy if it has a healthcheck, not restarting
  for c in "$@"; do
    s=$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}} r{{.RestartCount}}' "$c" 2>/dev/null || echo missing)
    check "container $c" '^running (healthy|-) r0$' "$s"
  done; }
http() { curl -s -m 10 -o /dev/null -w '%{http_code}' -A 'Mozilla/5.0 smoke-test' "$@"; }
HOME_IP=$(curl -s -m 8 https://ifconfig.me/ip)

echo "== Edge: Traefik, Cloudflare tunnel, CrowdSec"
check "traefik version"            '^3\.7\.15$' "$(docker exec traefik traefik version 2>/dev/null | awk '/Version:/{print $2}')"
check "public site (home)"         '^200$' "$(http https://home.holy-grail.ch/)"
check "scanner filter (/.env)"     '^403$' "$(http https://cloud.holy-grail.ch/.env)"
running cloudflared crowdsec
check "crowdsec version"           '^v1\.8\.1' "$(docker exec crowdsec cscli version 2>&1 | awk '/version:/{print $2}')"
check "crowdsec LAPI"              'successfully' "$(docker exec crowdsec cscli lapi status 2>&1 | tail -1)"
check "bouncer pulled < 10 min"    '^yes$' "$(docker exec crowdsec cscli bouncers list -o json 2>/dev/null | python3 -c 'import json,sys,datetime as d; n=d.datetime.now(d.timezone.utc); print("yes" if any(b.get("last_pull") and (n-d.datetime.fromisoformat(b["last_pull"].replace("Z","+00:00"))).total_seconds()<600 for b in json.load(sys.stdin)) else "no")')"

echo "== Authentik (SSO)"
running authentik-server authentik-worker authentik-postgresql
check "authentik version"          '2026\.8\.4' "$(docker inspect -f '{{.Config.Image}}' authentik-server)"
check "authentik postgres"         '^18\.' "$(docker exec authentik-postgresql postgres --version | awk '{print $3}')"
check "login page"                 '^200$' "$(http https://sso.holy-grail.ch/if/flow/default-authentication-flow/)"
check "OIDC discovery (Nextcloud)" '^200$' "$(http https://sso.holy-grail.ch/application/o/nextcloud/.well-known/openid-configuration)"
check "forward-auth (cup -> sso)"  'sso\.holy-grail\.ch' "$(curl -s -m 10 -o /dev/null -w '%{redirect_url}' https://cup.holy-grail.ch/)"
check "traefik dashboard -> sso"   'sso\.holy-grail\.ch' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve traefik.holy-grail.ch:443:192.168.1.2 https://traefik.holy-grail.ch/dashboard/)"
# SSO only: the old basicAuth router on :8080 is gone, nothing serves /dashboard/ there.
check "traefik no basicAuth (404)" '^404$' "$(http -H 'Host: fastpi.homelab' http://192.168.1.2:8080/dashboard/)"
# Grafana does its own OIDC: /login -> /login/generic_oauth -> Authentik authorize.
check "grafana login -> sso"       'sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -L --max-redirs 1 -o /dev/null -w '%{redirect_url}' --resolve grafana.holy-grail.ch:443:192.168.1.2 https://grafana.holy-grail.ch/login)"
# SSO only: the form client is unregistered, so POST /login is refused (400 notConfigured).
check "grafana login form disabled" 'auth\.client\.notConfigured' "$(curl -sk -m 10 --resolve grafana.holy-grail.ch:443:192.168.1.2 -H 'Content-Type: application/json' --data '{"user":"x","password":"x"}' https://grafana.holy-grail.ch/login)"
check "grafana not on LAN :3001"   '^000$' "$(http http://192.168.1.2:3001/api/health)"
# Portainer does its own OAuth (Custom provider -> Authentik); the internal password
# login (POST /api/auth) is refused by Traefik, and :9443 is bound to 127.0.0.1.
check "portainer via traefik"      '^200$' "$(http -k --resolve portainer.holy-grail.ch:443:192.168.1.2 https://portainer.holy-grail.ch/)"
check "portainer password POST 403" '^403$' "$(http -k --resolve portainer.holy-grail.ch:443:192.168.1.2 -H 'Content-Type: application/json' --data '{"username":"x","password":"x"}' https://portainer.holy-grail.ch/api/auth)"
check "portainer oauth validate"   'Unable to authenticate through OAuth' "$(curl -sk -m 10 --resolve portainer.holy-grail.ch:443:192.168.1.2 -H 'Content-Type: application/json' --data '{"code":"x"}' https://portainer.holy-grail.ch/api/auth/oauth/validate)"
check "portainer not on LAN :9443" '^000$' "$(http -k https://192.168.1.2:9443/api/status)"
check "portainer auth = oauth"     '"AuthenticationMethod":3' "$(curl -sk -m 5 https://127.0.0.1:9443/api/settings/public | tr -d ' ')"
check "portainer oauth -> sso"     'sso\.holy-grail\.ch/application/o/authorize/\?.*redirect_uri=https://portainer\.holy-grail\.ch/' "$(curl -sk -m 5 https://127.0.0.1:9443/api/settings/public)"
# AdGuard: forward auth + injected Basic creds (user authentik-proxy); break-glass = own login on :3000.
check "adguard ui -> sso"          'sso\.holy-grail\.ch' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve adguard.holy-grail.ch:443:192.168.1.2 https://adguard.holy-grail.ch/)"
check "adguard break-glass (401)"  '^40[13]$' "$(http http://192.168.1.2:3000/control/status)"
check "adguard local zone"         '^192\.168\.1\.2$' "$(dig +short @192.168.1.2 sso.holy-grail.ch | head -1)"

echo "== Monitoring"
running prometheus alertmanager grafana influxdb telegraf node-exporter blackbox-exporter json-exporter
check "influxdb"                   'v2\.9\.1.*pass|pass.*v2\.9\.1' "$(curl -s -m 5 http://127.0.0.1:8086/health)"
check "telegraf write errors (5m)" '^0$' "$(docker logs --since 5m telegraf 2>&1 | grep -c 'E! ')"
check "grafana db"                 '"ok"' "$(curl -s -m 5 http://127.0.0.1:3001/api/health | grep -o '"database": "[a-z]*"')"
check "alertmanager ready"         '^OK$' "$(curl -s -m 5 http://127.0.0.1:9093/-/ready)"
check "alertmanager not on LAN"    '^000$' "$(http http://192.168.1.2:9093/-/ready)"
check "prometheus targets down"    '^0$' "$(curl -s -m 5 'http://127.0.0.1:9090/api/v1/targets?state=active' | python3 -c 'import json,sys; t=json.load(sys.stdin)["data"]["activeTargets"]; print(sum(1 for x in t if x["health"]!="up"))')"

echo "== Apps on fastpi"
running adguardhome portainer audiobookshelf homeassistant clamav duckdns noip Cup homelab-dashboard claude-mockups backdrop-carousel stonks m4b-merge-dashboard m4b-auto-merge loyalty-sync socket-proxy-ro beefy-waker tower-waker
check "adguard resolves"           '^[0-9.]+$' "$(dig +short @127.0.0.1 example.com | head -1)"
check "portainer version"          '2\.45\.2' "$(curl -sk -m 5 https://127.0.0.1:9443/api/status)"
check "audiobookshelf"             '^200$' "$(http https://audiobookshelf.holy-grail.ch/)"
check "home assistant (LAN :8123)"  '^200$' "$(http http://192.168.1.2:8123/)"
check "home assistant via traefik"  '^200$' "$(http -k --resolve ha.holy-grail.ch:443:192.168.1.2 https://ha.holy-grail.ch/)"
# hass-oidc-auth: welcome sets the state cookie and 302s to /auth/oidc/redirect, whose page
# carries the (URL-quoted) Authentik authorize URL - proves trusted_proxies + https detection.
check "home assistant oidc -> sso"  'sso\.holy-grail\.ch/application/o/authorize/.*redirect_uri%3Dhttps%253A%252F%252Fha\.holy-grail\.ch%252Fauth%252Foidc%252Fcallback' "$(curl -sk -m 10 -L --max-redirs 2 -b '' --resolve ha.holy-grail.ch:443:192.168.1.2 https://ha.holy-grail.ch/auth/oidc/welcome | grep -o 'sso\.holy-grail\.ch/application/o/authorize/.*oidc%252Fcallback' | sed 's/client_id%3D[^%]*/client_id=…/')"
# SSO-only since 2026-10-18 (homeassistant: auth_providers: []): the only login provider
# must be auth_oidc - a "homeassistant" entry here means the password login is back.
check "home assistant sso-only"     '^auth_oidc$' "$(curl -s -m 5 http://192.168.1.2:8123/auth/providers | python3 -c 'import json,sys; print(",".join(p["type"] for p in json.load(sys.stdin)["providers"]))')"
check "m4b dashboard"              '^200$' "$(http http://192.168.1.2:8099/)"
check "stonks"                     '^(200|30[23])$' "$(http https://stonks.holy-grail.ch/)"
check "claude-mockups (auth)"      '^401$' "$(http https://claude-mockups.holy-grail.ch/)"
check "beefy waker"                '"up"' "$(curl -s -m 5 http://192.168.1.2:9001/status)"
check "tower waker v1.2.0"         '1\.2\.0' "$(curl -s -m 5 http://192.168.1.2:9002/nc | grep -o 'tower-waker [0-9.]*')"

echo "== VPN downloaders (gluetun pinned v3.41.3)"
running gluetun_mouse qbittorrent_mouse mousehole samba port_updater gluetun_nzb sabnzbd
for g in gluetun_mouse gluetun_nzb; do
  check "$g version"               'v3\.41\.3' "$(docker inspect -f '{{.Config.Image}}' $g)"; done
q=$(docker exec qbittorrent_mouse wget -qO- -T 8 https://ifconfig.me/ip 2>/dev/null)
if [[ -n $q && $q != "$HOME_IP" ]]; then ok "qbittorrent egress via VPN" "$q"; else bad "qbittorrent egress via VPN" "got: ${q:-none} (home $HOME_IP)"; fi
check "qbittorrent on Proton ASN"  'AS209103' "$(curl -s -m 8 https://ipinfo.io/$q/org)"
check "port-updater in sync"       'Port (OK|updated)' "$(docker logs --since 30m port_updater 2>&1 | grep -E 'Port (OK|updated)' | tail -1)"
check "mousehole -> MAM"           '"ok"' "$(curl -s -m 5 http://127.0.0.1:5010/health)"
# localhost-only host ports (SSO-only, 2026-10-19): nothing answers on the LAN IP.
check "sabnzbd (localhost :8090)"  '^200$' "$(http http://127.0.0.1:8090/)"
for p in 5010 8085 8087 8090; do check "port $p not on LAN"          '^000$' "$(http http://192.168.1.2:$p/)"; done

echo "== wg-easy (v15)"
check "wg-easy version"            '15\.4\.0' "$(docker inspect -f '{{.Config.Image}}' WireGuard-VPN)"
check "wireguard listening"        '51820' "$(docker exec WireGuard-VPN wg show wg0 listen-port)"
check "wireguard peers"            '^3$' "$(docker exec WireGuard-VPN wg show wg0 peers | wc -l)"
check "wg-easy UI (LAN https)"     '^200$' "$(curl -sk -m 10 -o /dev/null -w '%{http_code}' --resolve wg-easy.holy-grail.ch:443:192.168.1.2 'https://wg-easy.holy-grail.ch/login?auto_launch=false')"
check "wg-easy password login off" '"passwordDisabled":true' "$(curl -sk -m 10 --resolve wg-easy.holy-grail.ch:443:192.168.1.2 https://wg-easy.holy-grail.ch/api/auth/methods)"
check "wg-easy password POST (403)" '^403$' "$(curl -sk -m 10 -o /dev/null -w '%{http_code}' --resolve wg-easy.holy-grail.ch:443:192.168.1.2 -H 'Content-Type: application/json' --data '{"username":"x","password":"x","remember":false}' https://wg-easy.holy-grail.ch/api/auth/password)"
check "wg-easy oidc -> sso"        'sso\.holy-grail\.ch/application/o/authorize/\?redirect_uri=https%3A%2F%2Fwg-easy\.holy-grail\.ch%2Fapi%2Fauth%2Foidc%2Fcallback' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve wg-easy.holy-grail.ch:443:192.168.1.2 https://wg-easy.holy-grail.ch/api/auth/oidc)"

echo "== Digitec price tracker"
check "postgres version"           '^18\.' "$(docker exec digitec_db postgres --version | awk '{print $3}')"
check "web"                        '^200$' "$(http http://127.0.0.1:3002/)"

echo "== beefy (only if awake)"
if timeout 2 bash -c '</dev/tcp/192.168.1.102/22' 2>/dev/null; then
  r=$(timeout 60 ssh -o BatchMode=yes beefy 'echo "sec=$(apt list --upgradable 2>/dev/null | grep -c security)"; docker ps --format "{{.Names}} {{.Image}} {{.Status}}"' 2>/dev/null)
  check "beefy security updates"   'sec=0' "$(grep sec= <<<"$r")"
  check "portainer agent"          'portainer/agent:2\.45\.2 Up' "$(grep portainer <<<"$r")"
  for s in radarr prowlarr sabnzbd gluetun; do check "beefy $s up" "Up" "$(grep -i "$s" <<<"$r" | head -1)"; done
else skip "beefy" "asleep - not woken"; fi

echo "== tower (only if awake)"
if timeout 2 bash -c '</dev/tcp/192.168.1.101/22' 2>/dev/null; then
  check "nextcloud version"        '"versionstring":"34\.0\.5"' "$(curl -s -m 10 http://192.168.1.101:8080/status.php)"
  check "nextcloud /login -> SSO"  'user_oidc/login' "$(curl -s -m 10 -o /dev/null -w '%{redirect_url}' http://192.168.1.101:8080/login)"
  check "zfs pool"                 'ONLINE.*No known data errors' "$(timeout 20 ssh -o BatchMode=yes tower-direct 'zpool status data | grep -E "state:|errors:" | tr "\n" " "' 2>/dev/null)"
  check "no ZFS oops this boot"    '^0$' "$(timeout 20 ssh -o BatchMode=yes tower-direct 'grep -c "NULL pointer" /var/log/syslog' 2>/dev/null)"
else skip "tower" "asleep - not woken"; fi

echo; printf 'PASS %d   FAIL %d   SKIP %d\n' $PASS $FAIL $SKIP
(( FAIL == 0 ))
