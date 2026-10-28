# Avatar picker customizations (Docker/CUSTOMIZATIONS.md "Avatar-Picker").
APD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../Avatar-Picker" && pwd)
if want avatar-picker; then
  check avatar.local-pack '^[1-9][0-9]* local, 0 missing$' "$(docker exec avatar-picker python -c 'import json, os; g=[a["file"] for a in json.load(open("/app/gallery.json")) if a.get("pack") == "local"]; print(len(g), "local,", sum(not os.path.exists("/app/img-local/" + f) for f in g), "missing")' 2>&1 | tail -1)"
  check avatar.version '^same$' "$([[ $(docker exec avatar-picker cat /app/VERSION) == "$(cat "$APD/app/VERSION")" ]] && echo same || echo "image $(docker exec avatar-picker cat /app/VERSION) repo $(cat "$APD/app/VERSION")")"
  check avatar.favicon '^200 200$' "$(docker exec avatar-picker python -c 'import urllib.request as u; print(*(u.urlopen("http://127.0.0.1:8080/" + p, timeout=5).status for p in ("favicon.svg", "favicon-32.png")))' 2>&1 | tail -1)"
  check avatar.state '^200 groups=[0-9]+ avatars=[1-9][0-9]* lotr=[1-9]' "$(docker exec -i avatar-picker python - 2>&1 <<'PY' | tail -1
import json, urllib.error, urllib.request
s = open("/run/secrets/picker_secret").read().strip()
r = urllib.request.Request("http://127.0.0.1:8080/api/state", headers={"X-Picker-Secret": s, "X-authentik-username": "post-update-check"})
try:
    d = json.load(urllib.request.urlopen(r, timeout=15))
    print(200, f"groups={len(d['groups'])} avatars={len(d['avatars'])} lotr={sum(a.get('group') == 'lotr' for a in d['avatars'])}")
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode()[:60])
PY
)"
  check avatar.secret-required '^403$' "$(docker exec avatar-picker python -c 'import urllib.request as u, urllib.error as e
try: u.urlopen(u.Request("http://127.0.0.1:8080/api/state", headers={"X-authentik-username": "post-update-check"}), timeout=5); print(200)
except e.HTTPError as x: print(x.code)' 2>&1 | tail -1)"
  check avatar.queue '^ok$' "$(docker exec avatar-picker python -c 'import json; json.load(open("/data/queue.json")); print("ok")' 2>&1 | tail -1)"
  check avatar.img-routes '^200 403 200$' "$(read -r pk un < <(docker exec -i avatar-picker python - 2>&1 <<'PY'
import os, pathlib, sys
sys.path.insert(0, "/app")
import core, server
from authentik_api import Client
c = Client(os.environ["AUTHENTIK_URL"], pathlib.Path(os.environ["AUTHENTIK_TOKEN_FILE"]).read_text().strip())
picked = sorted(core.picked_ids(c.list_users(), os.environ["PUBLIC_BASE_URL"]) & server.IDS)
print(picked[0] if picked else "-", next(i for i in sorted(server.IDS) if i not in picked))
PY
); pub=$(dig +short sso.holy-grail.ch @1.1.1.1 | head -1); for t in "$pub $pk" "$pub $un" "192.168.1.2 $un"; do set -- $t; curl -s -m 10 -o /dev/null -w '%{http_code}\n' --resolve sso.holy-grail.ch:443:$1 "https://sso.holy-grail.ch/avatar-img/img/$2.png"; done | xargs)"
fi
check avatar.sync-units '^active enabled (success|)$' "$(echo "$(systemctl is-active avatar-sync.path) $(systemctl is-enabled avatar-sync.service) $(systemctl show avatar-sync.service -p Result --value)")"
check avatar.retry-timer '^(in sync inactive|pending [0-9]+ active)$' "$(echo "$(python3 "$APD/scripts/avatar-sync.py" --status 2>&1 | tail -1) $(systemctl is-active avatar-sync.timer)")"
check avatar.ha-pictures '^(ok [0-9]+/[0-9]+|inactive no token)$' "$(python3 "$APD/scripts/avatar-sync.py" --check ha 2>&1 | tail -1)"
