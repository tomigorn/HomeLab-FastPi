# Cup customizations (Docker/CUSTOMIZATIONS.md "Cup").
CUPD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../Cup" && pwd)
if want cup cup-agent-fastpi; then
  check cup.config '^socket=none servers=beefy,fastpi' "$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("socket=" + d["socket"], "servers=" + ",".join(sorted(d["servers"])))' "$CUPD/cup.json" 2>&1)"
  check cup.api-servers 'beefy.*fastpi' "$(curl -s -m 10 http://172.24.0.1:8000/api/v3/json | python3 -c 'import json,sys; print(sorted({i["server"] for i in json.load(sys.stdin)["images"]}))' 2>&1)"
  check cup.bind-172 '^000$' "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://192.168.1.2:8000/)"
  check cup.forward-auth 'sso\.holy-grail\.ch' "$(curl -s -m 10 -o /dev/null -w '%{redirect_url}' https://cup.holy-grail.ch/ | cut -c1-40)"
fi
