# Beefy waker customizations (Docker/CUSTOMIZATIONS.md "Beefy-Waker"): the app plus the host wake timers.
BWD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../Beefy-Waker" && pwd)
if want waker; then
  check waker.status '"up"' "$(curl -s -m 5 http://192.168.1.2:9001/status)"
  # ssh (the /history panel) refuses to run without a passwd entry for the compose uid
  check waker.ssh-user '^waker$' "$(docker exec beefy-waker sh -c 'getent passwd "$(id -u)" | cut -d: -f1' 2>&1)"
  check waker.wake-csrf '^403 403$' "$(u=http://192.168.1.2:9001/wake; echo "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST $u) $(curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST -H 'X-Wake: 1' -H 'Origin: https://evil.example.com' $u)")"   # D-11
  check waker.stream-auth '^401 401$' "$(u=http://192.168.1.2:9001/stream-auth; echo "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H 'X-Forwarded-Uri: /Videos/x/stream' $u) $(curl -s -m 5 -o /dev/null -w '%{http_code}' -H 'X-Emby-Token: bad"x' $u)")"
  # wake recovery: metrics textfile written, 10 signed-in gate addresses in Traefik (Docker/CUSTOMIZATIONS.md "Beefy-Waker")
  check beefy-waker.recovery '^1 10$' "$([[ -f /var/lib/node-exporter/textfile/beefy_wake.prom ]] && echo 1 || echo 0) $(cat "$BWD"/../Traefik/traefik/dynamic/*.yml | grep -c '9001/gate?port=[0-9]*&signed_in=1"')"
  # LAN wake route blanks the Authentik headers; every signed_in=1 gate sits behind authentik@file
  check beefy-waker.recovery-auth '^strip 11 ok$' "$(python3 -c 'import glob,sys,yaml;H=[(yaml.safe_load(open(p)) or {}).get("http") or {} for p in glob.glob(sys.argv[1]+"/*.yml")];g={n for h in H for n,m in (h.get("middlewares") or {}).items() if "signed_in=1" in str(((m or {}).get("forwardAuth") or {}).get("address",""))};R={n:[x.removesuffix("@file") for x in (r or {}).get("middlewares") or []] for h in H for n,r in (h.get("routers") or {}).items()};bad=[n for n,m in R.items() for i,x in enumerate(m) if x in g and "authentik" not in m[:i]];print("strip" if "beefy-wol-strip-authentik" in R.get("beefy-wol",[]) else "nostrip",sum(any(x in g for x in m) for m in R.values()),"ok" if not bad else "bad:"+",".join(bad))' "$BWD"/../Traefik/traefik/dynamic 2>&1)"
  check waker.version '^same$' "$(v=$(curl -s -m 5 http://192.168.1.2:9001/ | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -1); [[ $v == "v$(cat "$BWD/app/VERSION")" ]] && echo same || echo "page ${v:-none} repo $(cat "$BWD/app/VERSION")")"
fi
check waker.timers '^active active active active$' "$(systemctl is-active beefy-maintenance-wake.timer beefy-night-downloads-wake.timer beefy-night-downloads-poll.timer beefy-idle-pull.timer | xargs)"
check waker.units-installed '^same same same$' "$(for u in maintenance-wake/beefy-maintenance-wake night-downloads-wake/beefy-night-downloads-poll night-downloads-wake/beefy-night-downloads-wake; do cmp -s "$BWD/$u.service" /etc/systemd/system/${u#*/}.service && echo same || echo "${u#*/} differs"; done | xargs)"
check waker.night-wake-user '^pi$' "$(systemctl show -p User --value beefy-night-downloads-wake.service)"   # S-08: not root, the script is pi-writable
check waker.ssh-hooks '^2$' "$(grep -cE '^Match host (beefy|tower) exec' /home/pi/.ssh/config)"
