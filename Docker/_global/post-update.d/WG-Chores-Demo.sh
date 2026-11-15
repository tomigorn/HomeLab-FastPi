# WG Chores demo customizations (Docker/CUSTOMIZATIONS.md "WG-Chores-Demo"): local accounts, no registration, nightly reset.
if want wg-chores-demo; then
  IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' wg-chores-demo 2>/dev/null)
  check wgcdemo.hardening '^65035:65037 true \[ALL\] healthy$' "$(docker inspect -f '{{.Config.User}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}} {{.State.Health.Status}}' wg-chores-demo 2>&1)"
  check wgcdemo.healthz '^ok$' "$(curl -s -m 5 "http://$IP:8080/healthz")"
  check wgcdemo.config '^local=True registration=False oidc=None$' "$(curl -s -m 5 "http://$IP:8080/api/v1/config" | python3 -c 'import json,sys; c=json.load(sys.stdin); print("local=%s registration=%s oidc=%s" % (c["local_accounts"], c["open_registration"], c["oidc"]))' 2>&1)"
  check wgcdemo.route-headers '^200 csp hsts$' "$(curl -s -m 10 -o /dev/null -D - --resolve wg-chores-demo.holy-grail.ch:443:192.168.1.2 https://wg-chores-demo.holy-grail.ch/ | tr -d '\r' | awk 'NR==1{c=$2} tolower($0)~/^content-security-policy: default-src/{s=s" csp"} tolower($0)~/^strict-transport-security: max-age=31536000/{s=s" hsts"} END{print c s}')"
  check wgcdemo.reset-timer '^active enabled$' "$(echo "$(systemctl is-active wg-chores-demo-reset.timer) $(systemctl is-enabled wg-chores-demo-reset.timer 2>&1)")"
fi
