# Portainer customizations (Docker/CUSTOMIZATIONS.md "Portainer").
if want portainer; then
  check portainer.oauth-only '^"AuthenticationMethod":3$' "$(curl -sk -m 5 https://127.0.0.1:9443/api/settings/public | tr -d ' ' | grep -o '"AuthenticationMethod":[0-9]*')"
  check portainer.oauth-sso 'sso\.holy-grail\.ch/application/o/authorize/\?.*redirect_uri=https://portainer\.holy-grail\.ch/' "$(curl -sk -m 5 https://127.0.0.1:9443/api/settings/public | python3 -c 'import json,re,sys; print(re.sub(r"client_id=[^&]*", "client_id=x", json.load(sys.stdin)["OAuthLoginURI"]))' 2>&1)"
  check portainer.localhost-only '^000$' "$(curl -sk -m 5 -o /dev/null -w '%{http_code}' https://192.168.1.2:9443/api/status)"
fi
if want socket-proxy; then
  check portainer.proxy-readonly '^EXEC=0 POST=0$' "$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' portainer-socket-proxy | grep -E '^(POST|EXEC)=' | sort | xargs)"
fi
