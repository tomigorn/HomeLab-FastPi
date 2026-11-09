# mouse (VPN downloaders) customizations (Docker/CUSTOMIZATIONS.md "mouse"). Never greps the whole sabnzbd.ini: server sections hold account names.
QB=/mnt/seagate-red/qbittorrent/config/qBittorrent
SAB=/mnt/seagate-red/sabnzbd/config/sabnzbd.ini
if want prowlarr prowlarr-gate qbittorrent; then
  check mouse.prowlarr-setup '^OK MAM rules, gate and seed-forever hold$' "$(sudo -n python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../mouse" && pwd)/scripts/prowlarr-setup.py" --check 2>&1 | tail -1)"
fi
if want prowlarr prowlarr-gate; then
  check mouse.prowlarr-gate '^403$' "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://10.24.32.2:9697/)"
  check mouse.prowlarr-pin '2\.7\.0\.5723-ls167@sha256:431d7efebcef' "$(docker inspect -f '{{.Config.Image}}' prowlarr_mouse)"
  check mouse.prowlarr-lo-guard '^000 ok$' "$(docker exec qbittorrent_mouse curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:9696/ping) $(docker exec prowlarr-gate wget -q -O /dev/null http://127.0.0.1:9696/ping && echo ok)"
fi
if want qbittorrent; then
  # MAM flags qBittorrent 4.3.4-4.4.5 and 4.5.2-4.6.7 (owner 2026-11-09); any other version is allowed
  # MAM allows qBittorrent 5.0.1 to latest 5.2.x (list of 2026-11-09); anything not listed is rejected
  check mouse.qbit-mam-allowed '^v[0-9]+\.[0-9]+\.[0-9]+ allowed$' "$(docker exec qbittorrent_mouse /app/qbittorrent-nox --version 2>/dev/null | tail -1 | python3 -c 'import re,sys
m = re.search(r"v(\d+)\.(\d+)\.(\d+)", sys.stdin.read()); v = tuple(map(int, m.groups())) if m else None
print("v%d.%d.%d " % v + ("allowed" if (5, 0, 1) <= v < (5, 3, 0) else "discouraged" if any(a <= v <= b for a, b in [((4, 3, 4), (4, 4, 5)), ((4, 5, 2), (4, 6, 7))]) else "not-allowed") if v else "no version")')"
  # the tracker's verdict: MAM answered qBittorrent 5.3.0 "is not allowed" on 2026-11-09 although its list did not flag it
  check mouse.qbit-mam-accepted '^0 rejected [1-9][0-9]* working$' "$(for h in $(docker exec traefik wget -qO- -T 10 'http://10.24.25.2:8080/api/v2/torrents/info?limit=5&sort=added_on' 2>/dev/null | python3 -c 'import json,sys; print(" ".join(t["hash"] for t in json.load(sys.stdin)))' 2>/dev/null); do docker exec traefik wget -qO- -T 10 "http://10.24.25.2:8080/api/v2/torrents/trackers?hash=$h" 2>/dev/null; echo; done | python3 -c 'import json,sys
t = [x for l in sys.stdin if l.strip() for x in json.loads(l) if x["url"].startswith("http")]
print(sum("not allowed" in x["msg"] for x in t), "rejected", sum(x["status"] == 2 for x in t), "working")' 2>&1 | tail -1)"
  # through Traefik's auth bypass: every complete torrent in a seeding state, none in error or missingFiles
  check mouse.qbit-seeding '^([1-9][0-9]*) \1 0$' "$(docker exec traefik wget -qO- -T 10 http://10.24.25.2:8080/api/v2/torrents/info 2>/dev/null | python3 -c 'import json,sys
t = json.load(sys.stdin); done = [x for x in t if x["progress"] == 1]
print(len(done), sum(x["state"] in ("uploading", "stalledUP", "queuedUP", "forcedUP") for x in done), sum(x["state"] in ("error", "missingFiles") for x in t))' 2>&1 | tail -1)"
  # 5.2 keeps the WebUI\X keys in [Preferences], 5.3 moves them to a [WebUI] section: both read as WebUI\X
  check mouse.qbit-auth-bypass '^WebUI\\AuthSubnetWhitelist=10\.24\.25\.3/32 WebUI\\AuthSubnetWhitelistEnabled=true$' "$(python3 -c 'import re,sys
sec, out = "", {}
for l in open(sys.argv[1]):
    l = l.strip(); m = re.match(r"\[(.*)\]$", l)
    if m: sec = m.group(1); continue
    k, _, v = l.partition("="); k = k if sec == "Preferences" else sec + "\\" + k
    if k in ("WebUI\\AuthSubnetWhitelist", "WebUI\\AuthSubnetWhitelistEnabled", "WebUI\\ReverseProxySupportEnabled"): out[k] = v
print(" ".join(f"{k}={v}" for k, v in sorted(out.items())))' "$QB/qBittorrent.conf" 2>&1)"
  check mouse.qbit-bypass-scope '^403$' "$(docker exec audiobook-importer /audiobook-importer --probe http://10.24.25.2:8080/api/v2/app/version 2>&1)"
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
  check mouse.traefik-guard '^ok blocked$' "$(docker exec audiobook-importer /audiobook-importer --probe http://10.24.25.2:8080/ >/dev/null 2>&1 && echo ok) $(docker exec audiobookrequest python3 -c "import socket;s=socket.socket();s.settimeout(3);print('open' if s.connect_ex(('10.24.25.2',5010))==0 else 'blocked')" 2>/dev/null)"
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
if want samba; then
  # Host network: discovery and file service only on lo + eth0, never on a Docker bridge (D-14); encryption enforced.
  check mouse.samba-lan-only '^none Yes required$' "$(sudo -n ss -Hlntup 2>&1 | grep -E 'smbd|nmbd|wsdd2|avahi-daemon' | awk '{print $5}' | grep -E '%(br-|docker|veth)|^172\.' | xargs | sed 's/^$/none/') $(docker exec samba testparm -s -v 2>/dev/null | sed -n 's/^[[:space:]]*server smb encrypt = //p;s/^[[:space:]]*bind interfaces only = //p' | xargs)"
fi
if want autoheal-mouse; then
  check mouse.autoheal-pin '^willfarrell/autoheal:latest@sha256:4c7ed9f223b0' "$(docker inspect -f '{{.Config.Image}}' autoheal-mouse)"
  # the image's own unhealthy query (entrypoint functions) through socket-proxy-autoheal -> array, same count as docker ps
  check mouse.autoheal-sees '^array ([0-9]+) \1$' "$(echo "$(docker exec autoheal-mouse sh -c 'eval "$(sed "/^if \[ \"\$1\" = \"autoheal\" \]/,\$d" /docker-entrypoint)" >/dev/null; get_container_info | jq -r "type, length"' 2>&1 | xargs) $(docker ps -q --filter label=autoheal-mouse=true --filter health=unhealthy | wc -l)")"
fi
