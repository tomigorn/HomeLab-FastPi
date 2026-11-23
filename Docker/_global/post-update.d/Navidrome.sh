# Navidrome customizations (Docker/CUSTOMIZATIONS.md "Navidrome").
if want navidrome; then
  check navidrome.version-pin '^navidrome/navidrome:0\.64\.2$' "$(docker inspect -f '{{.Config.Image}}' navidrome 2>&1)"
  check navidrome.extauth '^172\.24\.255\.3/32 X-authentik-username$' "$(docker exec navidrome sh -c 'echo $ND_EXTAUTH_TRUSTEDSOURCES $ND_EXTAUTH_USERHEADER' 2>&1)"
  # a forged user header from an untrusted source (the container's own network address) gets no login
  check navidrome.forged-header '"status":"failed"' "$(docker exec navidrome wget -qO- -T 5 --header 'X-authentik-username: admin' 'http://navidrome:4533/rest/ping.view?v=1.16.1&c=post-update-check&f=json' 2>&1 | head -c 200)"
  check navidrome.music-readonly '^read-only$' "$(docker exec navidrome sh -c 'touch /music/.w 2>/dev/null && rm /music/.w && echo writable || echo read-only')"
  check navidrome.forward-auth '^https://sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve music.holy-grail.ch:443:192.168.1.2 https://music.holy-grail.ch/ | cut -c1-60)"
  # Basic auth is not intercepted (no app passwords): /rest without a Holy Grail session gets the login redirect, never Navidrome
  check navidrome.rest-basic-auth '^302 https://sso\.holy-grail\.ch/' "$(curl -sk -m 10 -o /dev/null -w '%{http_code} %{redirect_url}' -u nobody:wrong --resolve music.holy-grail.ch:443:192.168.1.2 'https://music.holy-grail.ch/rest/ping.view?v=1.16.1&c=check&f=json' | cut -c1-40)"  # deliberately wrong test credential; gitleaks:allow leak-check: ok
  check navidrome.ping '^ok$' "$(docker exec navidrome wget -qO /dev/null -T 5 http://127.0.0.1:4533/ping && echo ok)"
fi
