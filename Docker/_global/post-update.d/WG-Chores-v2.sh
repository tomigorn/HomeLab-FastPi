# WG Chores v2 customizations (Docker/CUSTOMIZATIONS.md "WG-Chores-v2"): own OIDC login (no forward auth), route with HSTS only, the app's own CSP.
if want wg-chores-v2; then
  IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' wg-chores-v2 2>/dev/null)
  check wgc.hardening '^65035:65037 true \[ALL\] healthy$' "$(docker inspect -f '{{.Config.User}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}} {{.State.Health.Status}}' wg-chores-v2 2>&1)"
  check wgc.healthz '^ok$' "$(curl -s -m 5 "http://$IP:8080/healthz")"
  check wgc.config '^local=False oidc=Holy Grail$' "$(curl -s -m 5 "http://$IP:8080/api/v1/config" | python3 -c 'import json,sys; c=json.load(sys.stdin); print("local=%s oidc=%s" % (c["local_accounts"], (c["oidc"] or {}).get("name")))' 2>&1)"
  check wgc.route-headers '^200 csp hsts$' "$(curl -s -m 10 -o /dev/null -D - --resolve wg-chores.holy-grail.ch:443:192.168.1.2 https://wg-chores.holy-grail.ch/ | tr -d '\r' | awk 'NR==1{c=$2} tolower($0)~/^content-security-policy: default-src/{s=s" csp"} tolower($0)~/^strict-transport-security: max-age=31536000/{s=s" hsts"} END{print c s}')"
  check wgc.no-forward-auth '^200$' "$(curl -s -m 10 -o /dev/null -w '%{http_code}' --resolve wg-chores.holy-grail.ch:443:192.168.1.2 https://wg-chores.holy-grail.ch/api/v1/config)"
fi
check wgc.oidc-issuer '^https://sso\.holy-grail\.ch/application/o/wg-chores/ RS256$' "$(curl -s -m 10 --resolve sso.holy-grail.ch:443:192.168.1.2 https://sso.holy-grail.ch/application/o/wg-chores/.well-known/openid-configuration | python3 -c 'import json,sys; c=json.load(sys.stdin); print(c["issuer"], " ".join(c["id_token_signing_alg_values_supported"]))' 2>&1)"
