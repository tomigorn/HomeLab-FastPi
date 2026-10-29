# Audiobook-Requests customizations (Docker/CUSTOMIZATIONS.md "Audiobook-Requests"). ABR settings are read with the API key, never printed.
ARD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../Audiobook-Requests" && pwd)
abr_get() { sudo -n cat "$ARD/secrets/abr_api_key" | python3 -c 'import json,sys,urllib.request
k = sys.stdin.read().strip()
r = urllib.request.Request("http://10.24.25.4:8000" + sys.argv[1], headers={"Authorization": "Bearer " + k})
d = json.load(urllib.request.urlopen(r, timeout=10))
print(eval(sys.argv[2], {"d": d}))' "$@" 2>&1 | tail -1; }
# books-proxy admits only Traefik and itself: direct checks run inside the container.
bp() { docker exec books-proxy curl -s -m 5 "$@"; }
BP=http://127.0.0.1:8080
if want abr; then
  check abr.image-pin '^markbeep/audiobookrequest:[0-9.]+@sha256:' "$(docker inspect -f '{{.Config.Image}}' audiobookrequest)"
  check abr.prowlarr-passthrough '^http://audiobook-importer:8000/prowlarr \[3030\]$' "$(abr_get /api/settings/prowlarr '" ".join(map(str, (d["base_url"], d["selected_categories"])))')"
  check abr.auto-download '^True$' "$(abr_get /api/settings/download 'd["auto_download"]')"
  check abr.webhook '^True http://audiobook-importer:8000/abr onSuccessfulDownload$' "$(abr_get /api/settings/notifications '" ".join(str(n.get(k)) for n in (d if isinstance(d, list) else d.get("notifications", [])) if n.get("name") == "audiobook-importer" for k in ("enabled", "url", "event"))')"
  check abr.abs-via-importer '^http://audiobook-importer:8000/abs True$' "$(abr_get /api/settings/audiobookshelf '" ".join(map(str, (d["abs_base_url"], d["abs_check_downloaded"])))')"
  check abr.oidc '^oidc abr_groups https None$' "$(abr_get /api/settings/security '" ".join(map(str, (d["login_type"], d["oidc_group_claim"], d["oidc_redirect_scheme"], d["force_login_type"])))')"
  check abr.oidc-redirect '^https://sso\.holy-grail\.ch/application/o/authorize/' "$(bp -o /dev/null -w '%{redirect_url}' $BP/auth/login | cut -c1-55)"
  check abr.forwarded-ips '^forwarded-allow-ips=10\.24\.25\.6$' "$(docker inspect -f '{{json .Config.Entrypoint}} {{json .Config.Cmd}}' audiobookrequest | grep -o 'forwarded-allow-ips=[0-9.]*' | head -1)"
fi
if want books-proxy; then
  check books.links-inject '^_hg/links\.js 1$' "$(echo "$(bp "$BP/auth/login?backup=1" | grep -o '_hg/links.js' | head -1) $(bp $BP/_hg/links.js | grep -c 'requests.holy-grail.ch')")"
  check books.all-requests '^200 401$' "$(echo "$(bp -o /dev/null -w '%{http_code}' $BP/_hg/requests/) $(bp -o /dev/null -w '%{http_code}' $BP/_hg/requests/data.json)")"
  check books.quota '^204 2$' "$(echo "$(docker exec books-proxy wget -q -S -O /dev/null --header 'X-Original-Method: GET' http://audiobook-importer:8000/quota 2>&1 | grep -o 'HTTP/1.[01] [0-9]*' | awk '{print $2}') $(docker exec books-proxy grep -c 'auth_request /_quota' /etc/nginx/nginx.conf)")"
  check books.bar-inject '^_hg/bar/bar\.css _hg/bar/bar\.js 200$' "$(echo $(bp "$BP/auth/login?backup=1" | grep -o '_hg/bar/bar\.[a-z]*' | sort -u) $(bp -o /dev/null -w '%{http_code}' $BP/_hg/bar/bar.js))"
  check books.bar-data '^fresh ok active$' "$(python3 -c 'import datetime as d,json,sys
j = json.load(sys.stdin); age = d.datetime.now(d.timezone.utc) - d.datetime.fromisoformat(j["generated"].replace("Z", "+00:00"))
print("fresh" if age.total_seconds() < 300 else "stale", "ok" if j["ok"] and j["storage"] else "not-ok")' < /var/lib/abr-bar/usage.json 2>&1 | tail -1) $(systemctl is-active abr-bar-usage.timer)"
  check books.bar-unauth '^302 sso 302 sso 302 sso 302 sso$' "$(cf=$(dig +short @1.1.1.1 books.holy-grail.ch A | grep -m1 -E '^[0-9.]+$'); for ip in 192.168.1.2 $cf; do for p in usage.json my-quota.json; do curl -s -m 10 -o /dev/null --resolve books.holy-grail.ch:443:$ip -w '%{http_code} %{redirect_url}\n' https://books.holy-grail.ch/_hg/bar/$p | sed -E 's#https://(sso)\.holy-grail\.ch/.*#\1#'; done; done | xargs)"
  check books.bar-needs-abr-session '^401 401$' "$(for p in usage.json my-quota.json; do bp -o /dev/null -w '%{http_code} ' "$BP/_hg/bar/$p"; done | xargs)"
  check books.mam-inject '^_hg/mam\.js 200$' "$(echo $(bp "$BP/auth/login?backup=1" | grep -o '_hg/mam\.js' | head -1) $(bp -o /dev/null -w '%{http_code}' $BP/_hg/mam.js))"
  check books.mam-unsatisfied '^ok [0-9]+/[0-9]+$' "$(python3 -c 'import json,sys
m = json.load(sys.stdin).get("mam") or {}
print("ok" if m.get("ok") else "not-ok", "%s/%s" % (m.get("unsatisfied"), m.get("limit")))' < /var/lib/abr-bar/usage.json 2>&1 | tail -1)"
  check books.library '^200 401 401 401 _hg/sizes\.js [1-9]$' "$(echo $(for p in /_hg/library/ /_hg/library/data.json /_hg/library/cover/x /_hg/sizes.json; do bp -o /dev/null -w '%{http_code} ' "$BP$p"; done) $(bp "$BP/auth/login?backup=1" | grep -o '_hg/sizes\.js' | head -1) $(bp $BP/_hg/links.js | grep -c '/_hg/library/'))"
  check books.peers-denied '^403 403 403 200$' "$(echo $(curl -s -m 5 -o /dev/null -w '%{http_code} ' http://10.24.25.6:8080/_hg/requests/data.json) $(curl -s -m 5 -o /dev/null -w '%{http_code} ' http://10.24.25.6:8080/) $(docker exec audiobook-importer wget -q -S -O /dev/null http://books-proxy:8080/_hg/requests/data.json 2>&1 | grep -o 'HTTP/1.[01] [0-9]*' | awk 'NR==1{print $2}') $(docker exec traefik wget -q -S -O /dev/null http://10.24.25.6:8080/_hg/health 2>&1 | grep -o 'HTTP/1.[01] [0-9]*' | awk 'NR==1{print $2}'))"
  check books.requests-unauth '^302 sso$' "$(curl -s -m 10 -o /dev/null --resolve books.holy-grail.ch:443:192.168.1.2 -w '%{http_code} %{redirect_url}' https://books.holy-grail.ch/_hg/requests/data.json | sed -E 's#https://(sso)\.holy-grail\.ch/.*#\1#')"
  check books.bar-shared '^(same|skipped: beefy not reachable \(not woken\))$' "$(bash "$ARD/scripts/sync-bar.sh" --check 2>&1 | tail -1)"
  check books.admin-only-downloads '^403 403$' "$(for p in /wishlist/hx-auto-download/B000CHECK0 /api/requests/B000CHECK0/auto-download; do bp -o /dev/null -w '%{http_code}\n' -X POST -H 'X-authentik-groups: streaming-requesters' "$BP$p"; done | xargs)"
fi
if want importer; then
  check importer.health '^ok$' "$(curl -s -m 5 http://10.24.25.5:8000/health)"
  check importer.library '^True 0 dict$' "$(echo $(docker exec books-proxy wget -q -O - --header 'X-authentik-username: post-update-nobody' http://audiobook-importer:8000/library | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["noAbsUser"], d["count"])' 2>&1 | tail -1) $(docker exec books-proxy wget -q -O - --header 'X-authentik-username: post-update-nobody' http://audiobook-importer:8000/sizes | python3 -c 'import json,sys; print(type(json.load(sys.stdin)).__name__)' 2>&1 | tail -1))"
  check importer.abs-readonly-gate '^404$' "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST http://10.24.25.5:8000/abs/api/libraries/x/scan)"
  check importer.callers '^403 403 403 403 403 403$' "$(for p in /quota /all-requests /prowlarr/torrent /library /library-cover/x /sizes; do curl -s -m 5 -o /dev/null -w '%{http_code}\n' "http://10.24.25.5:8000$p"; done | xargs)"
  check importer.post-callers '^403 403$' "$(for p in /abr /prowlarr/api/v1/search; do curl -s -m 5 -o /dev/null -w '%{http_code}\n' -X POST -d '{}' "http://10.24.25.5:8000$p"; done | xargs)"
  check importer.my-quota '^403 400$' "$(echo $(curl -s -m 5 -o /dev/null -w '%{http_code}' http://10.24.25.5:8000/my-quota) $(docker exec books-proxy wget -q -S -O /dev/null http://audiobook-importer:8000/my-quota 2>&1 | grep -o 'HTTP/1.[01] [0-9]*' | awk 'NR==1{print $2}'))"
  check importer.ranking-tests '^OK' "$(cd "$ARD/importer" && python3 -m unittest discover -s . 2>&1 | tail -1)"
fi
