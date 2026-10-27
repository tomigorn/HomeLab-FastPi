# LanguageTool customizations (Docker/CUSTOMIZATIONS.md "LanguageTool"); named after its compose dir LanguageTool/Raspi, as update-project.sh looks it up.
LTD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../LanguageTool" && pwd)
if want languagetool; then
  check lt.local-image '^languagetool-local:6\.8$' "$(docker inspect -f '{{.Config.Image}}' languagetool)"
  check lt.entrypoint-logback '/LanguageTool/logback\.xml' "$(docker exec languagetool sh -c 'ls /shared >/dev/null && tr "\0" " " < /proc/1/cmdline' | grep -o 'logback.configurationFile=[^ ]*')"
  check lt.rules-spelling '^PASS: [1-9][0-9]* +FAIL: 0$' "$(bash "$LTD/Raspi/scripts/test.sh" 2>&1 | grep -E 'PASS: [0-9]+ +FAIL: [0-9]+' | tail -1 | sed 's/^ *//')"
fi
