# AdGuard Home customizations (Docker/CUSTOMIZATIONS.md "adguard").
ADD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../adguard" && pwd)
if want adguardhome; then
  check adg.users '^\[.authentik-proxy.\] \[.auth_attempts: 5., .block_auth_min: 15.\]$' "$(sudo -n python3 -c 'import re,sys; t=open(sys.argv[1]).read(); print(re.findall(r"^\s+- name: (\S+)\n\s+password:", t, re.M), re.findall(r"auth_attempts: \d+|block_auth_min: \d+", t))' "$ADD/conf/AdGuardHome.yaml" 2>&1)"
  check adg.local-zone '^192\.168\.1\.2$' "$(dig +short +time=3 @192.168.1.2 sso.holy-grail.ch | head -1)"
  check adg.resolves '^[0-9.]+$' "$(dig +short +time=3 @192.168.1.2 example.com | head -1)"
  check adg.anon-refused '^40[13]$' "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://192.168.1.2:3000/control/status)"
  check adg.ui-sso 'sso\.holy-grail\.ch' "$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --resolve adguard.holy-grail.ch:443:192.168.1.2 https://adguard.holy-grail.ch/ | cut -c1-40)"
fi
