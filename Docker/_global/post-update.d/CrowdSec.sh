# CrowdSec customizations (Docker/CUSTOMIZATIONS.md "CrowdSec").
CSD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../CrowdSec" && pwd)
if want crowdsec; then
  check cs.collections '^ok$' "$(docker exec crowdsec cscli collections list -o json 2>/dev/null | python3 -c 'import json,sys; n={c["name"] for c in json.load(sys.stdin)["collections"] if c.get("status","").find("enabled")>=0 or c.get("local_version")}; w={"crowdsecurity/traefik","crowdsecurity/http-cve","crowdsecurity/base-http-scenarios"}; print("ok" if w<=n else "missing " + " ".join(sorted(w-n)))' 2>&1 | tail -1)"
  check cs.acquis-traefik '^[1-9]' "$(docker exec crowdsec cscli metrics show acquisition 2>/dev/null | grep -c 'traefik/access.log')"
  check cs.allowlist-home 'is allowlisted' "$(docker exec crowdsec cscli allowlists check "$(dig +short lang-tool.ddns.net @1.1.1.1 | tail -1)" 2>&1 | tail -1)"
  check cs.requests-signed-in '^PASS.*PASS.*PASS.*PASS' "$("$CSD"/tests/test_requests_whitelist.sh 2>&1 | xargs)"
  check cs.lapi 'successfully' "$(docker exec crowdsec cscli lapi status 2>&1 | tail -1)"
  check cs.bouncer-pull '^yes$' "$(docker exec crowdsec cscli bouncers list -o json 2>/dev/null | python3 -c 'import json,sys,datetime as d; n=d.datetime.now(d.timezone.utc); print("yes" if any(b.get("last_pull") and (n-d.datetime.fromisoformat(b["last_pull"].replace("Z","+00:00"))).total_seconds()<600 for b in json.load(sys.stdin)) else "no")')"
fi
check cs.units '^active active$' "$(systemctl is-active crowdsec-exporter.timer crowdsec-autoupdate.timer | xargs)"
