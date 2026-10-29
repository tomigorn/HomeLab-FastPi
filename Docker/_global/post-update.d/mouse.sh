# mouse (VPN downloaders) customizations (Docker/CUSTOMIZATIONS.md "mouse"). Never greps the whole sabnzbd.ini: server sections hold account names.
QB=/mnt/seagate-red/qbittorrent/config/qBittorrent
SAB=/mnt/seagate-red/sabnzbd/config/sabnzbd.ini
if want prowlarr prowlarr-gate qbittorrent; then
  check mouse.prowlarr-setup '^OK MAM rules, gate and seed-forever hold$' "$(sudo -n python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../mouse" && pwd)/scripts/prowlarr-setup.py" --check 2>&1 | tail -1)"
fi
if want prowlarr prowlarr-gate; then
  check mouse.prowlarr-gate '^403$' "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://10.24.32.2:9697/)"
  check mouse.prowlarr-pin '2\.7\.0\.5723-ls166@sha256:' "$(docker inspect -f '{{.Config.Image}}' prowlarr_mouse)"
  check mouse.prowlarr-lo-guard '^000 ok$' "$(docker exec qbittorrent_mouse curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:9696/ping) $(docker exec prowlarr-gate wget -q -O /dev/null http://127.0.0.1:9696/ping && echo ok)"
fi
if want qbittorrent; then
  check mouse.qbit-5.2-pin '^qBittorrent v5\.2\.' "$(docker exec qbittorrent_mouse /app/qbittorrent-nox --version 2>/dev/null | tail -1)"
  check mouse.qbit-auth-bypass '^WebUI\\AuthSubnetWhitelist=10\.24\.25\.3/32 WebUI\\AuthSubnetWhitelistEnabled=true$' "$(grep -E '^WebUI\\(AuthSubnetWhitelist|AuthSubnetWhitelistEnabled|ReverseProxySupportEnabled)=' "$QB/qBittorrent.conf" | xargs -d '\n')"
  check mouse.qbit-bypass-scope '403' "$(docker exec audiobook-importer python3 -c 'import urllib.request; urllib.request.urlopen("http://10.24.25.2:8080/api/v2/app/version", timeout=5)' 2>&1 | grep -o 'HTTP Error [0-9]*')"
  check mouse.qbit-vpn-bind '^Session\\Interface=tun0 Session\\InterfaceName=tun0$' "$(grep -E '^Session\\Interface(Name)?=' "$QB/qBittorrent.conf" | xargs -d '\n')"
  check mouse.qbit-category-abr '^/downloads/complete/abr -2 -2 -2$' "$(python3 -c 'import json,sys; c=json.load(open(sys.argv[1]))["abr"]; print(c["save_path"], c["ratio_limit"], c["seeding_time_limit"], c["inactive_seeding_time_limit"])' "$QB/categories.json" 2>&1)"
  check mouse.torrenting-port '^TORRENTING_PORT=' "$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' qbittorrent_mouse | grep '^TORRENTING_PORT=')"
fi
if want port-updater qbittorrent gluetun; then
  check mouse.port-updater-sync 'Port (OK|updated)' "$(docker logs --since 30m port_updater 2>&1 | grep -E 'Port (OK|updated)' | tail -1)"
  check mouse.port-updater-login '^401$' "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8087/)"
fi
if want gluetun; then
  check mouse.gluetun-pin ':v3\.41\.3$' "$(docker inspect -f '{{.Config.Image}}' gluetun_mouse)"
  check mouse.gluetun-server '^SERVER_HOSTNAMES=node-ch-07\.protonvpn\.net VPN_PORT_FORWARDING=on$' "$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' gluetun_mouse | grep -E '^(SERVER_HOSTNAMES|VPN_PORT_FORWARDING)=' | sort | xargs)"
  check mouse.gluetun-control-auth '^401 401$' "$(echo "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://10.24.32.2:8000/v1/portforward) $(curl -s -m 5 -o /dev/null -w '%{http_code}' http://10.24.32.2:8000/v1/vpn/status)")"
  check mouse.vpn-egress '^vpn$' "$(h=$(curl -s -m 8 https://ifconfig.me/ip); q=$(docker exec qbittorrent_mouse wget -qO- -T 8 https://ifconfig.me/ip 2>/dev/null); [[ -n $q && -n $h && $q != "$h" ]] && echo vpn || echo "home or none")"
fi
if want sabnzbd; then
  check mouse.sab-whitelist '^10\.24\.32\.0/24, 192\.168\.1\.0/24, 10\.24\.25\.3/32, 10\.24\.5\.5/32 \| True$' "$(python3 -c 'import re,sys
m = open(sys.argv[1]).read().split("[misc]")[1].split("\n[")[0]
g = lambda k: re.search(rf"^{k} = (.*)$", m, re.M).group(1)
print(g("local_ranges"), "|", "sabnzbd-audiobooks.holy-grail.ch" in g("host_whitelist"))' "$SAB" 2>&1)"
  check mouse.sab-localhost '^200$' "$(curl -s -m 10 -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/)"
fi
if want mousehole; then
  check mouse.mousehole-mam '"ok"' "$(curl -s -m 5 http://127.0.0.1:5010/health)"
fi
