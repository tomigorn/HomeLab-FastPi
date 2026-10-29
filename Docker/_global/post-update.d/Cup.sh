# Cup customizations (Docker/CUSTOMIZATIONS.md "Cup").
CUPD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../Cup" && pwd)
if want cup cup-agent-fastpi; then
  check cup.config '^socket=none servers=beefy,fastpi' "$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("socket=" + d["socket"], "servers=" + ",".join(sorted(d["servers"])))' "$CUPD/cup.json" 2>&1)"
  check cup.api-servers 'beefy.*fastpi' "$(curl -s -m 10 http://172.24.0.1:8000/api/v3/json | python3 -c 'import json,sys; print(sorted({i["server"] for i in json.load(sys.stdin)["images"]}))' 2>&1)"
  check cup.bind-172 '^000$' "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://192.168.1.2:8000/)"
  check cup.forward-auth 'sso\.holy-grail\.ch' "$(curl -s -m 10 -o /dev/null -w '%{redirect_url}' https://cup.holy-grail.ch/ | cut -c1-40)"
fi
# Rollback tags (rollback.invalid/..., UPDATE-RUNBOOK.md "Rollback tags") crash-loop Cup unless excluded, and hide an in-use image if they sort first.
if want cup cup-agent-fastpi; then
  check cup.exclude-rollback '^rollback.invalid/ ignore=True rollback.invalid/ ignore=True$' "$(for f in cup.json cup-agent.json; do python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(*[e for e in d["images"]["exclude"] if "rollback" in e], "ignore=%s" % d.get("registries", {}).get("rollback.invalid", {}).get("ignore"))' "$CUPD/$f"; done 2>&1 | xargs)"
  check cup.rollback-tags-last '^0 images$' "$(docker image ls -q | sort -u | xargs -r docker image inspect -f '{{join .RepoTags " "}}' 2>/dev/null | awk '$1 ~ /^rollback\.invalid\// && $NF !~ /^rollback\.invalid\// {n++} END {print n+0, "images"}')"
  a=$(docker inspect -f '{{.Name}} {{.State.Status}} {{.RestartCount}}' Cup cup-agent-fastpi 2>&1 | xargs); sleep 12
  b=$(docker inspect -f '{{.Name}} {{.State.Status}} {{.RestartCount}}' Cup cup-agent-fastpi 2>&1 | xargs)
  up=$(docker inspect -f '{{.State.StartedAt}}' Cup cup-agent-fastpi 2>/dev/null | while read -r t; do echo $(( $(date +%s) - $(date -d "$t" +%s) )); done | sort -n | head -1)
  check cup.no-crash-loop '^stable, up [0-9]{2,} s' "$([[ $a == "$b" && $b != *restarting* && $b != *exited* ]] && echo "stable, up ${up:-0} s: $b" || echo "restarting: $a -> $b")"
fi
