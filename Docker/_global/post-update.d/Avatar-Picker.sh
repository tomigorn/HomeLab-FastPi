# Avatar picker customizations (Docker/CUSTOMIZATIONS.md "Avatar-Picker").
APD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../Avatar-Picker" && pwd)
if want avatar-picker; then
  AP="docker exec avatar-picker /avatar-picker"
  check avatar.rust '^/avatar-picker healthy$' "$(echo "$(docker inspect -f '{{join .Config.Entrypoint " "}}' avatar-picker) $(docker inspect -f '{{.State.Health.Status}}' avatar-picker)")"
  check avatar.local-pack '^[1-9][0-9]* local, 0 missing$' "$($AP check local-pack 2>&1 | tail -1)"
  check avatar.version '^same$' "$([[ $($AP version) == "$(cat "$APD/app/VERSION")" ]] && echo same || echo "image $($AP version) repo $(cat "$APD/app/VERSION")")"
  check avatar.favicon '^200 200$' "$($AP check favicon 2>&1 | tail -1)"
  check avatar.state '^200 groups=[0-9]+ avatars=[1-9][0-9]* lotr=[1-9]' "$($AP check state post-update-check 2>&1 | tail -1)"
  check avatar.thumbs '^([1-9][0-9]*)/\1 thumbs, private immutable, gzip$' "$($AP check thumbs 2>&1 | tail -1)"
  check avatar.secret-required '^403$' "$($AP check secret-required 2>&1 | tail -1)"
  check avatar.queue '^ok$' "$($AP check queue 2>&1 | tail -1)"
  check avatar.img-routes '^200 403 200$' "$(read -r pk un < <($AP check picked 2>&1); pub=$(dig +short sso.holy-grail.ch @1.1.1.1 | head -1); for t in "$pub $pk" "$pub $un" "192.168.1.2 $un"; do set -- $t; curl -s -m 10 -o /dev/null -w '%{http_code}\n' --resolve sso.holy-grail.ch:443:$1 "https://sso.holy-grail.ch/avatar-img/img/$2.png"; done | xargs)"
fi
check avatar.sync-units '^active enabled (success|)$' "$(echo "$(systemctl is-active avatar-sync.path) $(systemctl is-enabled avatar-sync.service) $(systemctl show avatar-sync.service -p Result --value)")"
check avatar.retry-timer '^(in sync inactive|pending [0-9]+ active)$' "$(echo "$(python3 "$APD/scripts/avatar-sync.py" --status 2>&1 | tail -1) $(systemctl is-active avatar-sync.timer)")"
check avatar.ha-pictures '^(ok [0-9]+/[0-9]+|inactive no token)$' "$(python3 "$APD/scripts/avatar-sync.py" --check ha 2>&1 | tail -1)"
check avatar.token-rotate '^active ok$' "$(echo "$(systemctl is-active avatar-token-rotate.timer) $(awk '/^authentik_token_expires_timestamp_seconds/{print ($2 - systime() > 30 * 86400) ? "ok" : "expiring " $2}' /var/lib/node-exporter/textfile/authentik_tokens.prom 2>/dev/null)")"
