# Home Assistant customizations (Docker/CUSTOMIZATIONS.md "Home-Assistant").
HAD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../Home-Assistant" && pwd)
if want homeassistant; then
  check ha.sso-only '^auth_oidc$' "$(curl -s -m 5 http://192.168.1.2:8123/auth/providers | python3 -c 'import json,sys; print(",".join(p["type"] for p in json.load(sys.stdin)["providers"]))' 2>&1)"
  check ha.oidc-vendored '^"version": "1\.2\.1" clean$' "$(echo "$(grep -o '"version": "[^"]*"' "$HAD/config/custom_components/auth_oidc/manifest.json") $([[ -z $(git -C "$HAD" status --porcelain config/custom_components) ]] && echo clean || echo modified)")"
  check ha.oidc-redirect 'sso\.holy-grail\.ch/application/o/authorize/.*redirect_uri%3Dhttps%253A%252F%252Fha\.holy-grail\.ch%252Fauth%252Foidc%252Fcallback' "$(curl -sk -m 10 -L --max-redirs 2 -b '' --resolve ha.holy-grail.ch:443:192.168.1.2 https://ha.holy-grail.ch/auth/oidc/welcome | grep -o 'sso\.holy-grail\.ch/application/o/authorize/.*oidc%252Fcallback' | sed 's/client_id%3D[^%]*/client_id=x/')"
  check ha.http-trust '^True \[.172\.24\.0\.0/16.\]$' "$(sudo -n python3 -c 'import json,sys; d=json.load(open(sys.argv[1]))["data"]["stable"]; print(d["use_x_forwarded_for"], d["trusted_proxies"])' "$HAD/config/.storage/http" 2>&1)"
  check ha.via-traefik '^200$' "$(curl -sk -m 10 -o /dev/null -w '%{http_code}' --resolve ha.holy-grail.ch:443:192.168.1.2 https://ha.holy-grail.ch/)"
  check ha.zigbee-device '^ok$' "$(docker exec homeassistant test -e /dev/ttyUSB0 && echo ok)"
fi
check ha.person-pictures '^(ok [0-9]+/[0-9]+|inactive no token)$' "$(python3 "$HAD/../Avatar-Picker/scripts/avatar-sync.py" --check ha 2>&1 | tail -1)"
if want homeassistant; then
  check ha.plug-watch '^on on on on (on|off) (on|off) (on|off)$' "$(sudo -n sqlite3 -readonly "file:$HAD/config/home-assistant_v2.db?mode=ro" "select s.state from states_meta m join states s on s.state_id=(select max(state_id) from states where metadata_id=m.metadata_id) where m.entity_id in ('automation.plug_watch_beefy_lost_power_without_shutting_down','automation.plug_watch_relay_switched_without_a_home_assistant_command','automation.plug_watch_tower_lost_power_without_shutting_down','automation.plug_watch_test_alert','sensor.fastpi_plug_relay_stable','sensor.beefy_plug_relay_stable','sensor.tower_plug_relay_stable') order by m.entity_id" 2>&1 | xargs)"
  check ha.plug-watch-route '^telegram-power$' "$(docker exec alertmanager amtool config routes test --config.file=/etc/alertmanager/alertmanager.yml alertname=ServerPowerLost host=tower severity=critical 2>&1)"
fi
