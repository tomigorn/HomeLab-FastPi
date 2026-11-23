# Feishin customizations (Docker/CUSTOMIZATIONS.md "Feishin").
if want feishin; then
  check feishin.version-pin '^ghcr\.io/jeffvli/feishin:1\.17\.0$' "$(docker inspect -f '{{.Config.Image}}' feishin 2>&1)"
  check feishin.hardening '^65063:65063 ro=true caps=\[ALL\]$' "$(docker inspect -f '{{.Config.User}} ro={{.HostConfig.ReadonlyRootfs}} caps={{.HostConfig.CapDrop}}' feishin 2>&1)"
  # locked to the Navidrome on the same origin, Subsonic mode (the SSO header picks the user), no analytics
  check feishin.settings '^https://music\.holy-grail\.ch subsonic true true$' "$(docker exec feishin wget -qO- -T 5 http://127.0.0.1:9180/feishin/settings.js 2>&1 | sed -n 's/^window\.\(SERVER_TYPE\|SERVER_URL\|SERVER_LOCK\|ANALYTICS_DISABLED\) = "\(.*\)";$/\2/p' | xargs)"
  check feishin.health '^healthy$' "$(docker inspect -f '{{.State.Health.Status}}' feishin 2>&1)"
  check feishin.forward-auth '^https://sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve music.holy-grail.ch:443:192.168.1.2 https://music.holy-grail.ch/feishin/ | cut -c1-60)"
fi
