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
running() { # running <container...>  -> running, healthy if it has a healthcheck, no restart in the last 10 min (the lifetime count grows in outages)
  for c in "$@"; do
    s=$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}} r{{.RestartCount}} {{.State.StartedAt}}' "$c" 2>/dev/null || echo missing)
    read -r st he rc at <<<"$s"; up=$(( $(date +%s) - $(date -d "${at:-now}" +%s 2>/dev/null || date +%s) ))
    s="$st $he $rc up ${up}s"; [[ $rc != r0 ]] && (( up < 600 )) && s="$s restarted <10m"
    check "container $c" '^running (healthy|-) r[0-9]+ up [0-9]+s$' "$s"
  done; }
http() { curl -s -m 10 -o /dev/null -w '%{http_code}' -A 'Mozilla/5.0 smoke-test' "$@"; }
HOME_IP=$(curl -s -m 8 https://ifconfig.me/ip)

echo "== Edge: Traefik, Cloudflare tunnel, CrowdSec"
check "traefik version"            '^3\.7\.16$' "$(docker exec traefik traefik version 2>/dev/null | awk '/Version:/{print $2}')"
check "public site (home)"         '^200$' "$(http https://home.holy-grail.ch/)"
check "scanner filter (/.env)"     '^403$' "$(http https://cloud.holy-grail.ch/.env)"
running cloudflared crowdsec
check "cloudflared in host-guard ssh range" '^172\.20\.' "$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' cloudflared)"
check "host-guard rules.v4 persisted" '^1$' "$(grep -c '^-A INPUT -i br-+ -j HOST-GUARD$' /etc/iptables/rules.v4 2>/dev/null || sudo -n grep -c '^-A INPUT -i br-+ -j HOST-GUARD$' /etc/iptables/rules.v4)"
check "bouncer fails open"          '^stream -1$' "$(awk '/crowdsecMode:/{m=$2} /updateMaxFailure:/{f=$2} END{print m, f}' /home/pi/Projects/Docker/Traefik/traefik/dynamic/crowdsec.yml)"
check "crowdsec exporter < 15 min"  '^yes$' "$(s=$(sed -n 's/^crowdsec_exporter_last_success_timestamp_seconds //p' /var/lib/node-exporter/textfile/crowdsec_status.prom 2>/dev/null); (( $(date +%s) - ${s:-0} < 900 )) && echo yes || echo no)"
check "crowdsec version"           '^v1\.' "$(docker exec crowdsec cscli version 2>&1 | awk '/version:/{print $2}')"
check "crowdsec LAPI"              'successfully' "$(docker exec crowdsec cscli lapi status 2>&1 | tail -1)"
check "crowdsec home IP allowlisted" 'is allowlisted' "$(docker exec crowdsec cscli allowlists check "$(dig +short lang-tool.ddns.net @1.1.1.1 | tail -1)" 2>&1 | tail -1)"   # fails if the ISP changed the home IP
check "bouncer pulled < 10 min"    '^yes$' "$(docker exec crowdsec cscli bouncers list -o json 2>/dev/null | python3 -c 'import json,sys,datetime as d; n=d.datetime.now(d.timezone.utc); print("yes" if any(b.get("last_pull") and (n-d.datetime.fromisoformat(b["last_pull"].replace("Z","+00:00"))).total_seconds()<600 for b in json.load(sys.stdin)) else "no")')"
# The vendored Traefik bouncer plugin is updated by hand: the exporter compares version.go with
# upstream and with what the running bouncer reports (CrowdSec README "Updating the bouncer plugin").
check "bouncer plugin version exported" "^installed=\"$(sed -n 's/.*pluginVersion = "\([^"]*\)".*/\1/p' /home/pi/Projects/Docker/Traefik/traefik/plugins-local/src/github.com/maxlerebourg/crowdsec-bouncer-traefik-plugin/version.go)\"" "$(grep -o 'installed="[^"]*"' /var/lib/node-exporter/textfile/crowdsec.prom 2>/dev/null | head -1)"
check "bouncer plugin current + running" '^0 0$' "$(awk '/^crowdsec_bouncer_plugin_outdated /{o=$2} /^crowdsec_bouncer_reported_version_mismatch /{m=$2} END{print o, m}' /var/lib/node-exporter/textfile/crowdsec.prom 2>/dev/null)"
# Threat data freshness (CrowdSec README "Threat data refresh"): community list every 2 h,
# hub content + GeoIP checked daily at 05:07 by crowdsec-autoupdate.timer.
age() { s=$(sed -n "s/^$1 //p" /var/lib/node-exporter/textfile/$2 2>/dev/null | head -1); s=${s%.*}; echo $(( $(date +%s) - ${s:-0} )); }
check "community list pulled < 3 h" '^yes$' "$(a=$(age crowdsec_capi_last_pull_timestamp_seconds crowdsec.prom); (( a < 10800 )) && echo yes || echo "no (${a}s)")"
check "community list > 10k IPs"   '^yes$' "$(n=$(curl -s -m 5 -G --data-urlencode 'query=sum(cs_active_decisions{origin="CAPI"})' http://127.0.0.1:9090/api/v1/query | python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(int(float(r[0]["value"][1])) if r else 0)'); (( ${n:-0} > 10000 )) && echo yes || echo "no (${n:-?})")"
check "hub/GeoIP checked < 36 h"   '^yes$' "$(a=$(age crowdsec_autoupdate_last_run_timestamp_seconds crowdsec_autoupdate.prom); (( a < 129600 )) && echo yes || echo "no (${a}s)")"
# Community-list IPs (one IPv4, one IPv6) must be refused by Traefik (proves the bouncer syncs CAPI decisions). Via the
# container IP + Cf-Connecting-Ip (as cloudflared delivers it), so the probe never bans the home IP.
# Only decisions with > 10 min left: cscli also lists expired ones (negative duration) until they are flushed, and those rightly pass.
tip=$(docker inspect traefik -f '{{(index .NetworkSettings.Networks "traefik_proxy").IPAddress}}' 2>/dev/null)
cips=$(docker exec crowdsec cscli decisions list -o json --origin CAPI 2>/dev/null | python3 -c '
import json,re,sys
def left(d): m=re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:[\d.]+s)?", d); return int(m[1] or 0)*60+int(m[2] or 0) if m and d else 0
ds=[d for a in json.load(sys.stdin) or [] for d in a["decisions"] if d["type"]=="ban" and d["scope"]=="Ip" and left(d["duration"])>10]
print(*[next((d["value"] for d in ds if (":" in d["value"])==v6), "") for v6 in (False, True)])' 2>/dev/null)
check "community IPs blocked (403 403)" '^403 403 \[' "$(for c in $cips; do [[ -n $tip ]] && curl -sk -m 10 -o /dev/null -w '%{http_code} ' --resolve "home.holy-grail.ch:443:$tip" -H "Cf-Connecting-Ip: $c" https://home.holy-grail.ch/; done | sed 's/ $//') [${cips:-no CAPI IP}]"
check "clean IP passes (200)"        '^200$' "$(curl -sk -m 10 -o /dev/null -w '%{http_code}' --resolve "home.holy-grail.ch:443:$tip" -H "Cf-Connecting-Ip: 203.0.113.7" https://home.holy-grail.ch/)"   # TEST-NET-3, never on a list

echo "== Authentik (SSO)"
running authentik-server authentik-worker authentik-postgresql
check "authentik version"          '2026\.8\.5' "$(docker inspect -f '{{.Config.Image}}' authentik-server)"
check "authentik postgres"         '^18\.' "$(docker exec authentik-postgresql postgres --version | awk '{print $3}')"
check "login page"                 '^200$' "$(http https://sso.holy-grail.ch/if/flow/default-authentication-flow/)"
check "OIDC discovery (Nextcloud)" '^200$' "$(http https://sso.holy-grail.ch/application/o/nextcloud/.well-known/openid-configuration)"
check "forward-auth (cup -> sso)"  'sso\.holy-grail\.ch' "$(curl -s -m 10 -o /dev/null -w '%{redirect_url}' https://cup.holy-grail.ch/)"
check "traefik dashboard -> sso"   'sso\.holy-grail\.ch' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve traefik.holy-grail.ch:443:192.168.1.2 https://traefik.holy-grail.ch/dashboard/)"
# :8080 (metrics entrypoint) is not published: only Prometheus reaches it over traefik_metrics.
check "traefik :8080 not on LAN"   '^000$' "$(http http://192.168.1.2:8080/metrics)"
check "traefik metrics (prometheus)" 'traefik_entrypoint_requests_total' "$(docker exec prometheus wget -qO- -T 5 http://traefik:8080/metrics 2>/dev/null | grep -m1 -o traefik_entrypoint_requests_total)"
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
# AdGuard: forward auth + injected Basic creds (user authentik-proxy, the only user; no human login).
# beefy media stack behind forward auth (sonarr: streaming-admins, requests/Seerr: streaming-users).
for a in sonarr requests; do check "$a -> sso"               'sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve $a.holy-grail.ch:443:192.168.1.2 https://$a.holy-grail.ch/ | cut -c1-60)"; done
check "adguard ui -> sso"          'sso\.holy-grail\.ch' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve adguard.holy-grail.ch:443:192.168.1.2 https://adguard.holy-grail.ch/)"
check "adguard anon refused (401)" '^40[13]$' "$(http http://192.168.1.2:3000/control/status)"
# qBittorrent/VPN status pages (homelab-admins). port_updater keeps its Basic login, Authentik injects it.
for a in vpn-status-beefy vpn-status-mouse; do check "$a -> sso"   'sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve $a.holy-grail.ch:443:192.168.1.2 https://$a.holy-grail.ch/ | cut -c1-60)"; done
# fastpi audiobook downloaders (streaming-admins), Traefik over traefik_mouse.
for a in qbittorrent-audiobooks sabnzbd-audiobooks prowlarr-audiobooks books; do check "$a -> sso"   'sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve $a.holy-grail.ch:443:192.168.1.2 https://$a.holy-grail.ch/ | cut -c1-60)"; done
check "port_updater anon refused (401)" '^401$' "$(http http://127.0.0.1:8087/)"
check "adguard local zone"         '^192\.168\.1\.2$' "$(dig +short @192.168.1.2 sso.holy-grail.ch | head -1)"

echo "== Monitoring"
running prometheus alertmanager grafana influxdb telegraf node-exporter blackbox-exporter blackbox-exporter-wan json-exporter
check "influxdb"                   'v2\.9\.1.*pass|pass.*v2\.9\.1' "$(curl -s -m 5 http://127.0.0.1:8086/health)"
check "telegraf write errors (5m)" '^0$' "$(docker logs --since 5m telegraf 2>&1 | grep -c 'E! ')"
check "grafana db"                 '"ok"' "$(curl -s -m 5 http://127.0.0.1:3001/api/health | grep -o '"database": "[a-z]*"')"
# The Grafana API needs a login (basic auth off, SSO only), so provisioned dashboards are read from Grafana's own DB.
grafana_dashboards() { local d; d=$(mktemp); docker exec grafana cat /var/lib/grafana/grafana.db > "$d" 2>/dev/null; python3 -c 'import sqlite3,sys; c=sqlite3.connect(f"file:{sys.argv[1]}?mode=ro",uri=True); w=sys.argv[2:]; n={r[0] for r in c.execute("select name from resource where resource=\"dashboards\"")}; print("ok" if all(x in n for x in w) else "missing " + " ".join(x for x in w if x not in n))' "$d" "$@" 2>&1 | tail -1; rm -f "$d"; }
check "grafana dashboards provisioned" '^ok$' "$(grafana_dashboards crowdsec-overview updates-security)"
check "alertmanager ready"         '^OK$' "$(curl -s -m 5 http://127.0.0.1:9093/-/ready)"
check "alertmanager not on LAN"    '^000$' "$(http http://192.168.1.2:9093/-/ready)"
check "prometheus targets down"    '^0$' "$(curl -s -m 5 'http://127.0.0.1:9090/api/v1/targets?state=active' | python3 -c 'import json,sys; t=json.load(sys.stdin)["data"]["activeTargets"]; print(sum(1 for x in t if x["health"]!="up"))')"
check "container exporter < 3 min"  '^yes$' "$(s=$(sed -n 's/^container_exporter_last_success_timestamp_seconds //p' /var/lib/node-exporter/textfile/container_exporter_status.prom 2>/dev/null); (( $(date +%s) - ${s:-0} < 180 )) && echo yes || echo no)"
check "containers expected but down" '^0$' "$(curl -s -m 5 -G --data-urlencode 'query=count(container_expected_running == 1 and container_running == 0) or vector(0)' http://127.0.0.1:9090/api/v1/query | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["result"][0]["value"][1])')"
check "container + reboot rules loaded" '^ok$' "$(curl -s -m 5 http://127.0.0.1:9090/api/v1/rules | python3 -c 'import json,sys; n={r["name"] for g in json.load(sys.stdin)["data"]["groups"] for r in g["rules"]}; w={"ContainerDown","ContainerCrashLooping","ContainerUnhealthy","ContainerExporterStale","HostRebooted","HostRebootedUnclean"}; print("ok" if w<=n else "missing " + " ".join(sorted(w-n)))')"

echo "== Apps on fastpi"
running adguardhome portainer audiobookshelf prowlarr_mouse prowlarr-gate audiobookrequest audiobook-importer books-proxy homeassistant clamav duckdns noip Cup homelab-dashboard claude-mockups server-specs wiki backdrop-carousel stonks m4b-merge-dashboard m4b-auto-merge loyalty-sync socket-proxy-ro beefy-waker tower-waker
check "prowlarr MAM rules, gate, seeding" '^OK MAM rules, gate and seed-forever hold$' "$(sudo -n python3 /home/pi/Projects/Docker/mouse/scripts/prowlarr-setup.py --check 2>&1 | tail -1)"
check "books public -> sso"         'sso\.holy-grail\.ch/application/o/authorize/' "$(curl -s -m 10 -o /dev/null -w '%{redirect_url}' -A 'Mozilla/5.0 smoke-test' --resolve books.holy-grail.ch:443:$(dig +short @1.1.1.1 books.holy-grail.ch | head -1) https://books.holy-grail.ch/ | cut -c1-60)"
check "prowlarr UI closed to non-Traefik" '^403$' "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://10.24.32.2:9697/)"
check "books-proxy serves Seerr link"  '^1$' "$(curl -s -m 5 http://10.24.25.6:8080/_hg/links.js | grep -c 'requests.holy-grail.ch')"
check "importer /abs passes no POST"  '^404$' "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST http://10.24.25.5:8000/abs/api/libraries/x/scan)"
check "importer health"            '^ok$' "$(curl -s -m 5 http://10.24.25.5:8000/health)"
check "clamav-scan timer active"   '^active$' "$(systemctl is-active clamav-scan.timer)"
check "clamav-hostscan timer active" '^active$' "$(systemctl is-active clamav-hostscan.timer)"
if [[ -f /var/lib/node-exporter/textfile/clamav.prom ]]; then
  check "clamav nightly scan < 2 days" '^yes$' "$(s=$(sed -n 's/^clamav_last_run_timestamp_seconds{.*mode="new"} //p' /var/lib/node-exporter/textfile/clamav.prom); (( $(date +%s) - ${s:-0} < 172800 )) && echo yes || echo "no (${s:-none})")"
else skip "clamav nightly scan < 2 days" "no clamav.prom yet"; fi
check "security timers active"     '^active active active active active$' "$(systemctl is-active security-scan.timer security-image-scan.timer security-av.timer security-av-hits.timer security-audit.timer | xargs)"
rules_loaded() { curl -s -m 5 http://127.0.0.1:9090/api/v1/rules | python3 -c 'import json,sys; n={r["name"] for g in json.load(sys.stdin)["data"]["groups"] for r in g["rules"] if r.get("health")=="ok"}; w=sys.argv[1:]; print("ok" if all(x in n for x in w) else "missing " + " ".join(x for x in w if x not in n))' "$@"; }
check "antivirus rules loaded"     '^ok$' "$(rules_loaded MalwareQuarantined MalwareFound ClamavScanStale ClamavScanErrors ClamavSignaturesStale)"
check "digest rule loaded"         '^ok$' "$(rules_loaded WeeklyUpdateDigest homelab:local_utc_offset_hours)"
check "adguard resolves"           '^[0-9.]+$' "$(dig +short @127.0.0.1 example.com | head -1)"
check "portainer version"          '2\.45\.3' "$(curl -sk -m 5 https://127.0.0.1:9443/api/status)"
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
check "claude-mockups -> sso"      '^https://sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve claude-mockups.holy-grail.ch:443:192.168.1.2 https://claude-mockups.holy-grail.ch/ | cut -c1-60)"
check "server-specs -> sso"       '^https://sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve specs.holy-grail.ch:443:192.168.1.2 https://specs.holy-grail.ch/ | cut -c1-60)"
check "wiki -> sso"              '^https://sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve wiki.holy-grail.ch:443:192.168.1.2 https://wiki.holy-grail.ch/ | cut -c1-60)"
check "claude-mockups inbox POST -> sso" '^https://sso\.holy-grail\.ch/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve claude-mockups.holy-grail.ch:443:192.168.1.2 -X POST --data '{}' https://claude-mockups.holy-grail.ch/_inbox/submit | cut -c1-40)"
check "beefy waker"                '"up"' "$(curl -s -m 5 http://192.168.1.2:9001/status)"
check "tower waker v1.2.0"         '1\.2\.0' "$(curl -s -m 5 http://192.168.1.2:9002/nc | grep -o 'tower-waker [0-9.]*')"
# Avatar picker loads its state (needs Authentik's user list; 503 = Authentik unreachable, the 2026-10-25 regression).
# Asked inside the container with the Traefik header secret, which is read there and never printed.
running avatar-picker
check "avatar picker state"        '^200 groups=[0-9]+ avatars=[1-9][0-9]* lotr=[1-9]' "$(docker exec -i avatar-picker python - 2>&1 <<'PY' | tail -1
import json, urllib.error, urllib.request
s = open("/run/secrets/picker_secret").read().strip()
r = urllib.request.Request("http://127.0.0.1:8080/api/state", headers={"X-Picker-Secret": s, "X-authentik-username": "smoke-test"})
try:
    d = json.load(urllib.request.urlopen(r, timeout=15))
    print(200, f"groups={len(d['groups'])} avatars={len(d['avatars'])} lotr={sum(a.get('group') == 'lotr' for a in d['avatars'])}")
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode()[:60])
PY
)"

echo "== Tracker (Floppy on beefy; containers + backup in the beefy section)"
check "tracker -> sso"             'sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve tracker.holy-grail.ch:443:192.168.1.2 https://tracker.holy-grail.ch/ | cut -c1-60)"
check "tracker /go -> sso"         'sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve tracker.holy-grail.ch:443:192.168.1.2 https://tracker.holy-grail.ch/go/tmdb/movie/603 | cut -c1-60)"
check "tracker OIDC discovery"     '^200$' "$(http https://sso.holy-grail.ch/application/o/tracker-login/.well-known/openid-configuration)"
# Floppy's token URLs (webhooks, calendar, Stremio, ListenBrainz) are refused for everyone: the token is a full API key.
check "tracker token URLs LAN 403" '^403 403 403 403$' "$(for p in /webhook/jellyfin/smoke /calendar/download/smoke /stremio-addon/smoke/manifest.json /apis/listenbrainz/1/validate-token; do curl -sk -m 10 -o /dev/null -w '%{http_code} ' -X POST --resolve tracker.holy-grail.ch:443:192.168.1.2 "https://tracker.holy-grail.ch$p"; done | sed 's/ $//')"
# fastpi resolves tracker to the LAN (AdGuard), so the public check pins the Cloudflare edge IP.
cfip=$(dig +short tracker.holy-grail.ch @1.1.1.1 | grep -E '^[0-9.]+$' | head -1)
if [[ -n $cfip ]]; then
  check "tracker webhook public 403" '^403$' "$(http -X POST --resolve tracker.holy-grail.ch:443:$cfip https://tracker.holy-grail.ch/webhook/jellyfin/smoke)"
else skip "tracker webhook public 403" "no public hostname for tracker"; fi

echo "== Dependency-Track (beefy, homelab-admins)"
check "dt -> sso"                  'sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve dt.holy-grail.ch:443:192.168.1.2 https://dt.holy-grail.ch/ | cut -c1-60)"
check "dt OIDC discovery"          '^200$' "$(http https://sso.holy-grail.ch/application/o/dt-login/.well-known/openid-configuration)"

echo "== VPN downloaders (gluetun pinned v3.41.3)"
running gluetun_mouse qbittorrent_mouse mousehole samba port_updater sabnzbd
check "gluetun_mouse version"      'v3\.41\.3' "$(docker inspect -f '{{.Config.Image}}' gluetun_mouse)"
q=$(docker exec qbittorrent_mouse wget -qO- -T 8 https://ifconfig.me/ip 2>/dev/null)
if [[ -n $q && $q != "$HOME_IP" ]]; then ok "qbittorrent egress via VPN" "$q"; else bad "qbittorrent egress via VPN" "got: ${q:-none} (home $HOME_IP)"; fi
check "qbittorrent on Proton ASN"  'AS209103' "$(curl -s -m 8 https://ipinfo.io/$q/org)"
# SABnzbd shares gluetun_mouse since 2026-10-24 (Docker/nzb retired).
check "sabnzbd egress via VPN"     "^${q:-none}\$" "$(docker exec sabnzbd curl -s -m 8 https://ifconfig.me/ip 2>/dev/null)"
check "port-updater in sync"       'Port (OK|updated)' "$(docker logs --since 30m port_updater 2>&1 | grep -E 'Port (OK|updated)' | tail -1)"
check "mousehole -> MAM"           '"ok"' "$(curl -s -m 5 http://127.0.0.1:5010/health)"
# localhost-only host ports (SSO-only, 2026-10-19): nothing answers on the LAN IP.
check "sabnzbd (localhost :8090)"  '^200$' "$(http http://127.0.0.1:8090/)"
check "cup api (172.24.0.1:8000)"  '"images"' "$(curl -s -m 10 http://172.24.0.1:8000/api/v3/json | head -c 20)"
for p in 3002 5000 5432 5010 8000 8083 8084 8085 8087 8088 8089 8090 8978; do check "port $p not on LAN"          '^000$' "$(http http://192.168.1.2:$p/)"; done

echo "== wg-easy (v15)"
check "wg-easy version"            '15\.5\.0' "$(docker inspect -f '{{.Config.Image}}' WireGuard-VPN)"
check "wireguard listening"        '51820' "$(docker exec WireGuard-VPN wg show wg0 listen-port)"
check "wireguard peers"            '^3$' "$(docker exec WireGuard-VPN wg show wg0 peers | wc -l)"
check "wg-easy UI (LAN https)"     '^200$' "$(curl -sk -m 10 -o /dev/null -w '%{http_code}' --resolve wg-easy.holy-grail.ch:443:192.168.1.2 'https://wg-easy.holy-grail.ch/login?auto_launch=false')"
check "wg-easy password login off" '"passwordDisabled":true' "$(curl -sk -m 10 --resolve wg-easy.holy-grail.ch:443:192.168.1.2 https://wg-easy.holy-grail.ch/api/auth/methods)"
check "wg-easy password POST (403)" '^403$' "$(curl -sk -m 10 -o /dev/null -w '%{http_code}' --resolve wg-easy.holy-grail.ch:443:192.168.1.2 -H 'Content-Type: application/json' --data '{"username":"x","password":"x","remember":false}' https://wg-easy.holy-grail.ch/api/auth/password)"
check "wg-easy oidc -> sso"        'sso\.holy-grail\.ch/application/o/authorize/\?redirect_uri=https%3A%2F%2Fwg-easy\.holy-grail\.ch%2Fapi%2Fauth%2Foidc%2Fcallback' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve wg-easy.holy-grail.ch:443:192.168.1.2 https://wg-easy.holy-grail.ch/api/auth/oidc)"

echo "== Digitec price tracker"
# Digitec is intentionally offline (2026-10-21, not productive yet): skip its
# checks while stopped so the suite reflects reality. Restart it and these run again.
if docker ps --format '{{.Names}}' | grep -q '^digitec_web$'; then
  check "postgres version"           '^18\.' "$(docker exec digitec_db postgres --version | awk '{print $3}')"
  check "web"                        '^200$' "$(http http://127.0.0.1:3002/)"
else
  skip "digitec postgres version" "digitec intentionally offline"
  skip "digitec web"              "digitec intentionally offline"
fi

echo "== beefy (only if awake)"
if timeout 2 bash -c '</dev/tcp/192.168.1.102/22' 2>/dev/null; then
  r=$(timeout 60 ssh -o BatchMode=yes beefy 'echo "sec=$(apt list --upgradable 2>/dev/null | grep -c security)"; sudo docker ps --format "{{.Names}} {{.Image}} {{.Status}}"; f=$(sudo find /srv/appdata/floppy/backups/database -name "db-*.sqlite3" -mmin -2880 2>/dev/null | head -1); echo "floppybackup=$([[ -n $f ]] && echo yes || echo no)"' 2>/dev/null)
  check "beefy security updates"   'sec=0' "$(grep sec= <<<"$r")"
  check "portainer agent"          'portainer/agent:2\.45\.3 Up' "$(grep portainer <<<"$r")"
  for s in radarr sonarr prowlarr sabnzbd gluetun seerr; do check "beefy $s up" "Up" "$(grep -i "$s" <<<"$r" | head -1)"; done
  for s in floppy floppy-redis; do check "beefy $s healthy" "^$s .*\(healthy\)" "$(grep "^$s " <<<"$r")"; done
  check "floppy version"           'floppy:26\.10\.22 ' "$(grep '^floppy ' <<<"$r")"
  check "floppy snapshot < 2 days" '^floppybackup=yes$' "$(grep floppybackup= <<<"$r")"
else skip "beefy" "asleep - not woken"; fi

echo "== tower (only if awake)"
if timeout 2 bash -c '</dev/tcp/192.168.1.101/22' 2>/dev/null; then
  check "nextcloud version"        '"versionstring":"34\.0\.5"' "$(curl -s -m 10 http://192.168.1.101:8080/status.php)"
  check "nextcloud /login -> SSO"  'user_oidc/login' "$(curl -s -m 10 -o /dev/null -w '%{redirect_url}' http://192.168.1.101:8080/login)"
  check "btrfs pool raid1"         'Data, ?RAID1.*Metadata, ?RAID1' "$(timeout 20 ssh -o BatchMode=yes tower-direct 'btrfs filesystem df /mnt/data | tr "\n" " "' 2>/dev/null)"
  check "btrfs device errors"      '^0$' "$(timeout 20 ssh -o BatchMode=yes tower-direct 'btrfs device stats /mnt/data | awk "{s+=\$2} END {print s+0}"' 2>/dev/null)"
  check "no kernel oops this boot" '^0$' "$(timeout 20 ssh -o BatchMode=yes tower-direct 'grep -cE "NULL pointer|general protection" /var/log/syslog' 2>/dev/null)"
  check "cup agent (fastpi only)"  '"images"' "$(curl -s -m 10 http://192.168.1.101:8000/api/v3/json | head -c 20)"
  check "cup agent DOCKER-USER"    '! -s 192\.168\.1\.2/32 -i br0 -p tcp -m tcp --dport 8000 -j DROP' "$(timeout 20 ssh -o BatchMode=yes tower-direct 'iptables -S DOCKER-USER' 2>/dev/null)"
  # Cup only fetches agents at its own refresh; tower asleep then = no tower images until the next one.
  n=$(curl -s -m 10 http://172.24.0.1:8000/api/v3/json | python3 -c 'import json,sys; print(sum(i.get("server")=="tower" for i in json.load(sys.stdin)["images"]))' 2>/dev/null)
  if (( ${n:-0} > 0 )); then ok "cup lists server tower" "$n images"
  elif docker logs Cup 2>&1 | grep -E 'Checked [0-9]+ images|101:8000/api/v3/refresh: Failed' | tail -2 | head -1 | grep -q Failed; then skip "cup lists server tower" "tower asleep at the last Cup refresh"
  else bad "cup lists server tower" "got: ${n:-no answer}"; fi
else skip "tower" "asleep - not woken"; fi

echo; printf 'PASS %d   FAIL %d   SKIP %d\n' $PASS $FAIL $SKIP
(( FAIL == 0 ))
