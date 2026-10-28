# Audiobook-Requests customizations (Docker/CUSTOMIZATIONS.md "Audiobook-Requests"). ABR settings are read with the API key, never printed.
ARD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../Audiobook-Requests" && pwd)
abr_get() { sudo -n cat "$ARD/secrets/abr_api_key" | python3 -c 'import json,sys,urllib.request
k = sys.stdin.read().strip()
r = urllib.request.Request("http://10.24.25.4:8000" + sys.argv[1], headers={"Authorization": "Bearer " + k})
d = json.load(urllib.request.urlopen(r, timeout=10))
print(eval(sys.argv[2], {"d": d}))' "$@" 2>&1 | tail -1; }
if want abr; then
  check abr.image-pin '^markbeep/audiobookrequest:[0-9.]+@sha256:' "$(docker inspect -f '{{.Config.Image}}' audiobookrequest)"
  check abr.prowlarr-passthrough '^http://audiobook-importer:8000/prowlarr \[3030\]$' "$(abr_get /api/settings/prowlarr '" ".join(map(str, (d["base_url"], d["selected_categories"])))')"
  check abr.auto-download '^True$' "$(abr_get /api/settings/download 'd["auto_download"]')"
  check abr.webhook '^True http://audiobook-importer:8000/abr onSuccessfulDownload$' "$(abr_get /api/settings/notifications '" ".join(str(n.get(k)) for n in (d if isinstance(d, list) else d.get("notifications", [])) if n.get("name") == "audiobook-importer" for k in ("enabled", "url", "event"))')"
  check abr.abs-via-importer '^http://audiobook-importer:8000/abs True$' "$(abr_get /api/settings/audiobookshelf '" ".join(map(str, (d["abs_base_url"], d["abs_check_downloaded"])))')"
  check abr.oidc '^oidc abr_groups https None$' "$(abr_get /api/settings/security '" ".join(map(str, (d["login_type"], d["oidc_group_claim"], d["oidc_redirect_scheme"], d["force_login_type"])))')"
  check abr.oidc-redirect '^https://sso\.holy-grail\.ch/application/o/authorize/' "$(curl -s -m 5 -o /dev/null -w '%{redirect_url}' http://10.24.25.6:8080/auth/login | cut -c1-55)"
  check abr.forwarded-ips '^forwarded-allow-ips=10\.24\.25\.6$' "$(docker inspect -f '{{json .Config.Entrypoint}} {{json .Config.Cmd}}' audiobookrequest | grep -o 'forwarded-allow-ips=[0-9.]*' | head -1)"
fi
if want books-proxy; then
  check books.links-inject '^_hg/links\.js 1$' "$(echo "$(curl -s -m 5 'http://10.24.25.6:8080/auth/login?backup=1' | grep -o '_hg/links.js' | head -1) $(curl -s -m 5 http://10.24.25.6:8080/_hg/links.js | grep -c 'requests.holy-grail.ch')")"
  check books.all-requests '^200 \[$' "$(echo "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://10.24.25.6:8080/_hg/requests/) $(curl -s -m 5 http://10.24.25.6:8080/_hg/requests/data.json | head -c1)")"
  check books.quota '^204 2$' "$(echo "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H 'X-Original-Method: GET' http://10.24.25.5:8000/quota) $(docker exec books-proxy grep -c 'auth_request /_quota' /etc/nginx/nginx.conf)")"
  check books.admin-only-downloads '^403 403$' "$(for p in /wishlist/hx-auto-download/B000CHECK0 /api/requests/B000CHECK0/auto-download; do curl -s -m 5 -o /dev/null -w '%{http_code}\n' -X POST -H 'X-authentik-groups: streaming-requesters' "http://10.24.25.6:8080$p"; done | xargs)"
fi
if want importer; then
  check importer.health '^ok$' "$(curl -s -m 5 http://10.24.25.5:8000/health)"
  check importer.abs-readonly-gate '^404$' "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST http://10.24.25.5:8000/abs/api/libraries/x/scan)"
  check importer.ranking-tests '^OK' "$(cd "$ARD/importer" && python3 -m unittest discover -s . 2>&1 | tail -1)"
fi
