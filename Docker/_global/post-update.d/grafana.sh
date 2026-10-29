# Monitoring stack customizations (Docker/CUSTOMIZATIONS.md "grafana").
GFD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../grafana" && pwd)
if want grafana; then
  check grafana.oauth-login 'sso\.holy-grail\.ch/application/o/authorize/' "$(curl -sk -m 10 -L --max-redirs 1 -o /dev/null -w '%{redirect_url}' --resolve grafana.holy-grail.ch:443:192.168.1.2 https://grafana.holy-grail.ch/login | cut -c1-55)"
  check grafana.login-form-off 'auth\.client\.notConfigured' "$(curl -sk -m 10 --resolve grafana.holy-grail.ch:443:192.168.1.2 -H 'Content-Type: application/json' --data '{"user":"x","password":"x"}' https://grafana.holy-grail.ch/login)"
  check grafana.basic-auth-off '^401$' "$(curl -s -m 5 -o /dev/null -w '%{http_code}' --user "$(printf 'nobody:%s' "$RANDOM")" http://127.0.0.1:3001/api/org)"
  check grafana.dashboards '^ok$' "$(docker exec grafana cat /var/lib/grafana/grafana.db | python3 -c 'import json,sqlite3,sys,glob
c = sqlite3.connect(":memory:"); c.deserialize(sys.stdin.buffer.read())
n = {r[0] for r in c.execute("select name from resource where resource=\"dashboards\"")}
w = [json.load(open(f))["uid"] for f in glob.glob(sys.argv[1] + "/*.json")]
print("ok" if w and all(x in n for x in w) else "missing " + " ".join(x for x in w if x not in n))' "$GFD/provisioning/dashboards" 2>&1 | tail -1)"
fi
if want prometheus; then
  check prom.rule-files '^([0-9]+) \1 \[\] 0$' "$(curl -s -m 5 http://127.0.0.1:9090/api/v1/rules | python3 -c 'import json,os,sys
g = json.load(sys.stdin)["data"]["groups"]; f = {os.path.basename(x["file"]) for x in g}; d = set(os.listdir(sys.argv[1]))
print(len(f), len(d), sorted(d - f), sum(r.get("health") != "ok" for x in g for r in x["rules"]))' "$GFD/prometheus/rules")"
  check prom.retention '^400d 60GiB$' "$(curl -s -m 5 http://127.0.0.1:9090/api/v1/status/flags | python3 -c 'import json,sys; d=json.load(sys.stdin)["data"]; print(d["storage.tsdb.retention.time"], d["storage.tsdb.retention.size"])')"
  check prom.scrape-jobs '^([0-9]+) \1 0$' "$(echo "$(grep -c 'job_name:' "$GFD/prometheus/prometheus.yml") $(curl -s -m 5 'http://127.0.0.1:9090/api/v1/targets?state=active' | python3 -c 'import json,sys; t=json.load(sys.stdin)["data"]["activeTargets"]; print(len({x["scrapePool"] for x in t}), sum(x["health"] != "up" for x in t))')")"
fi
if want alertmanager; then
  check am.config '^True True True telegram\.tmpl$' "$(echo "$(curl -s -m 5 http://127.0.0.1:9093/api/v2/status | python3 -c 'import json,sys; c=json.load(sys.stdin)["config"]["original"]; print("quiet-hours" in c, "Europe/Zurich" in c, "templates/" in c)') $(docker exec alertmanager ls /etc/alertmanager/templates | xargs)")"
  check am.routes '^telegram critical null telegram-digest$' "$(for l in severity=warning severity=critical notify=digest alertname=DailyDigest; do docker exec alertmanager amtool config routes test --config.file=/etc/alertmanager/alertmanager.yml alertname=X $l; done | xargs)"
  check am.routing-tests 'OK|passed' "$(python3 "$GFD/alertmanager/test_routing.py" "$GFD/alertmanager/alertmanager.yml" 2>&1 | tail -1)"
fi
if want blackbox-exporter blackbox-exporter-wan; then
  check blackbox.modules '^([1-9][0-9]*) \1$' "$(for c in blackbox-exporter blackbox-exporter-wan; do docker exec $c wget -qO- -T 5 http://127.0.0.1:9115/config | grep -cE '^    [a-z_0-9]+:$'; done | xargs)"
fi
if want telegraf; then
  check telegraf.writes '^0$' "$(docker logs --since 5m telegraf 2>&1 | grep -c 'E! \[outputs')"
fi
if want influxdb; then
  check influxdb.v2-pin 'v2\.9\.1.*pass|pass.*v2\.9\.1' "$(curl -s -m 5 http://127.0.0.1:8086/health)"
fi
if want node-exporter; then
  check node.textfile-collector '^0 [1-9][0-9]*$' "$(curl -s -m 5 -G --data-urlencode 'query=node_textfile_scrape_error' http://127.0.0.1:9090/api/v1/query | python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else "none")') $(ls /var/lib/node-exporter/textfile/*.prom | wc -l)"
fi
check grafana.host-timers '^active active active active active$' "$(systemctl is-active container-exporter.timer usage-collector.timer status-exporter.timer status-exporter-daily.timer smart-exporter.timer | xargs)"
check grafana.status-exporter '^yes [1-9][0-9]*$' "$(s=$(sed -n 's/^tls_cert_exporter_last_run_timestamp_seconds //p' /var/lib/node-exporter/textfile/status_certs.prom 2>/dev/null); (( $(date +%s) - ${s:-0} < 2 * 86400 )) && echo yes || echo no) $(grep -c '^tls_cert_probe_success.* 1$' /var/lib/node-exporter/textfile/status_certs.prom 2>/dev/null)"
check grafana.smart-exporter '^yes 0$' "$(s=$(sed -n 's/^smart_exporter_last_run_timestamp_seconds{host="fastpi"} //p' /var/lib/node-exporter/textfile/smart_fastpi.prom 2>/dev/null); (( $(date +%s) - ${s:-0} < 7200 )) && echo yes || echo no) $(sed -n 's/^smart_exporter_errors{host="fastpi"} //p' /var/lib/node-exporter/textfile/smart_fastpi.prom 2>/dev/null)"
check grafana.container-exporter '^yes$' "$(s=$(sed -n 's/^container_exporter_last_success_timestamp_seconds //p' /var/lib/node-exporter/textfile/container_exporter_status.prom 2>/dev/null); s=${s%.*}; (( $(date +%s) - ${s:-0} < 180 )) && echo yes || echo no)"
