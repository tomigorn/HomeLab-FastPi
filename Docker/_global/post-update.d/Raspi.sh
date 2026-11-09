# LanguageTool customizations (Docker/CUSTOMIZATIONS.md "LanguageTool"); named after its compose dir LanguageTool/Raspi, as update-project.sh looks it up.
LTD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../LanguageTool" && pwd)
if want languagetool; then
  check lt.local-image '^languagetool-local:6\.8$' "$(docker inspect -f '{{.Config.Image}}' languagetool)"
  check lt.entrypoint-logback '/LanguageTool/logback\.xml' "$(docker exec languagetool sh -c 'ls /shared >/dev/null && tr "\0" " " < /proc/1/cmdline' | grep -o 'logback.configurationFile=[^ ]*')"
  check lt.rules-spelling '^PASS: [1-9][0-9]* +FAIL: 0$' "$(bash "$LTD/Raspi/scripts/test.sh" 2>&1 | grep -E 'PASS: [0-9]+ +FAIL: [0-9]+' | tail -1 | sed 's/^ *//')"
  check lt.jvm-gc '^G1PeriodicGCInterval=300000 concurrent gclog$' "$(o=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' languagetool | grep '^JAVA_TOOL_OPTIONS='); echo "$(grep -o 'G1PeriodicGCInterval=[0-9]*' <<<"$o") $(grep -q -- '-XX:-G1PeriodicGCInvokesConcurrent' <<<"$o" && echo full || echo concurrent) $(docker exec languagetool test -s /tmp/gc.log && echo gclog || echo no-gclog)")"
  check lt.pipeline-pool '^5 1024m 1610612736$' "$(echo "$(docker exec languagetool sh -c 'sed -n "s/^maxPipelinePoolSize=//p" config.properties') $(docker top languagetool -eo pid,args | grep -o -- ' -Xmx[0-9]*[mg]' | head -1 | sed 's/ -Xmx//') $(cat /sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' languagetool).scope/memory.max 2>/dev/null)")"
fi
