#!/usr/bin/env bash
# exporters-scraped.sh [container...]: each exporter was scraped by Prometheus since it started, and every scrape since then is up (auto-update CHECK).
set -uo pipefail
t=$(curl -sf -m 10 'http://127.0.0.1:9090/api/v1/targets?state=active') || { echo "FAIL prometheus targets API"; exit 1; }
(( $# )) || set -- node-exporter blackbox-exporter blackbox-exporter-wan json-exporter
rc=0
for c in "$@"; do
  started=$(docker inspect -f '{{.State.StartedAt}}' "$c" 2>/dev/null) || { echo "FAIL $c: no container"; rc=1; continue; }
  r=$(jq -r --arg c "$c" --arg s "$started" 'def ts: sub("\\.[0-9]+"; "") | fromdateiso8601;
    [.data.activeTargets[] | select(.scrapeUrl | contains("//" + $c + ":")) | select((.lastScrape | ts) > ($s | ts))]
    | "\(length) \(map(select(.health != "up")) | length)"' <<<"$t") || { echo "FAIL $c: bad targets JSON"; rc=1; continue; }
  read -r fresh down <<<"$r"
  if (( fresh > 0 && down == 0 )); then echo "OK $c: $fresh scrapes since start, all up"; else echo "FAIL $c: $fresh scrapes since start, $down down"; rc=1; fi
done
exit $rc
