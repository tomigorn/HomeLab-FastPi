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
check dsp.image-pin '^pinned 4/4, running = pin 4/4$' "$(docker compose --project-directory "$DSPD" config --format json 2>/dev/null | python3 -c 'import json, subprocess, sys
s = {k: v for k, v in json.load(sys.stdin)["services"].items() if k in sys.argv[1:]}
i = lambda *a: subprocess.run(["docker", *a], capture_output=True, text=True).stdout.strip()
p = sum("@sha256:" in v["image"] for v in s.values())
r = sum(i("image", "inspect", "-f", "{{.Id}}", v["image"]) == i("inspect", "-f", "{{.Image}}", v["container_name"]) != "" for v in s.values())
print(f"pinned {p}/{len(s)}, running = pin {r}/{len(s)}")' socket-proxy-ro socket-proxy-autoheal socket-proxy-portupdater socket-proxy-unix)"   # A-30
