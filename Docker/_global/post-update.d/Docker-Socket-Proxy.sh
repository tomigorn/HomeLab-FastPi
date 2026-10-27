# Docker socket proxy customizations (Docker/CUSTOMIZATIONS.md "Docker-Socket-Proxy"): env allow-lists and haproxy overlays.
DSPD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../Docker-Socket-Proxy" && pwd)
if want socket-proxy-ro; then
  check dsp.ro-env '^CONTAINERS EVENTS IMAGES INFO PING VERSION$' "$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' socket-proxy-ro | grep -E '=1$' | cut -d= -f1 | sort | xargs)"
  check dsp.ro-denies-post '^200 403$' "$(echo "$(docker exec telegraf curl -s -m 5 -o /dev/null -w '%{http_code}' http://socket-proxy-ro:2375/version) $(docker exec telegraf curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST http://socket-proxy-ro:2375/containers/post-update-check/restart)")"
fi
if want socket-proxy-autoheal socket-proxy-portupdater; then
  check dsp.haproxy-overlays '^match match$' "$(for c in autoheal portupdater; do [[ $(docker exec socket-proxy-$c cat /usr/local/etc/haproxy/haproxy.cfg | sha256sum) == "$(sha256sum < "$DSPD/$c-haproxy.cfg")" ]] && echo match || echo "$c differs"; done | xargs)"
  check dsp.autoheal-denies '^403$' "$(docker exec autoheal-mouse curl -s -m 5 -o /dev/null -w '%{http_code}' http://socket-proxy-autoheal:2375/info)"
  check dsp.portupdater-scope '^200 403$' "$(echo "$(docker exec port_updater curl -s -m 5 -o /dev/null -w '%{http_code}' http://socket-proxy-portupdater:2375/containers/gluetun_mouse/json) $(docker exec port_updater curl -s -m 5 -o /dev/null -w '%{http_code}' http://socket-proxy-portupdater:2375/containers/traefik/json)")"
fi
