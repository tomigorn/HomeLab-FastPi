# wg-easy customizations (Docker/CUSTOMIZATIONS.md "WireguardVPN").
WGD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../WireguardVPN" && pwd)
if want wg-easy; then
  check wg.oidc-env '^DISABLE_PASSWORD_AUTH=true OAUTH_AUTO_LAUNCH=oidc OAUTH_AUTO_REGISTER=false OAUTH_PROVIDERS=oidc$' "$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' WireGuard-VPN | grep -E '^(DISABLE_PASSWORD_AUTH|OAUTH_AUTO_LAUNCH|OAUTH_AUTO_REGISTER|OAUTH_PROVIDERS)=' | sort | xargs)"
  check wg.password-off '"passwordDisabled":true' "$(curl -sk -m 10 --resolve wg-easy.holy-grail.ch:443:192.168.1.2 https://wg-easy.holy-grail.ch/api/auth/methods)"
  check wg.password-post '^403$' "$(curl -sk -m 10 -o /dev/null -w '%{http_code}' --resolve wg-easy.holy-grail.ch:443:192.168.1.2 -H 'Content-Type: application/json' --data '{"username":"x","password":"x","remember":false}' https://wg-easy.holy-grail.ch/api/auth/password)"
  check wg.oidc-sso 'sso\.holy-grail\.ch/application/o/authorize/\?redirect_uri=https%3A%2F%2Fwg-easy\.holy-grail\.ch%2Fapi%2Fauth%2Foidc%2Fcallback' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve wg-easy.holy-grail.ch:443:192.168.1.2 https://wg-easy.holy-grail.ch/api/auth/oidc)"
  check wg.secret-entrypoint 'oidc_client_secret' "$(docker inspect -f '{{json .Config.Entrypoint}}' WireGuard-VPN | grep -o 'oidc_client_secret' | head -1)"
  check wg.dnat-hook '^1$' "$(docker exec WireGuard-VPN iptables-nft -t nat -S PREROUTING 2>/dev/null | grep -c 'DNAT --to-destination 10.24.5.3')"
  check wg.hooks-nft '^\[\(5, 0, True\), \(5, 0, True\)\]$' "$(sudo -n python3 -c 'import re,sqlite3,sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); r = c.execute("select post_up, post_down from hooks_table").fetchone()
print([(v.count("iptables-nft"), len(re.findall(r"iptables(?!-nft)", v)), "10.24.5.3" in v) for v in r])' "$WGD/wg-easy-v15/wg-easy.db" 2>&1 | tail -1)"
  check wg.listening '^51820$' "$(docker exec WireGuard-VPN wg show wg0 listen-port)"
fi
