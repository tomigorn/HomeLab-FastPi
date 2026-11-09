#!/usr/bin/env bash
# Runs the new importer image next to the live one and compares what both answer for the same requests (README "Rust importer").
#   bash sidebyside.sh [image]      default audiobook-importer:local; SBS_KEEP=1 leaves the container running
# Scratch: ~/.cache/claude-work/importer-sbs (a copy of data/, an empty library). Read-only against ABS and ABR; qBittorrent and
# Prowlarr are out of reach from this network (the live importer's address is the only one gluetun admits).
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
proj=$(cd "$here/../.." && pwd)
export IMPORTER_IMAGE=${1:-audiobook-importer:local}
export SBS_SCRATCH=${SBS_SCRATCH:-$HOME/.cache/claude-work/importer-sbs}
export SBS_HOST_IP=${SBS_HOST_IP:-$(docker network inspect audiobook-requests_egress -f '{{(index .IPAM.Config 0).Gateway}}')}
compose() { docker compose --project-directory "$here/sidebyside" -p audiobook-importer-sbs "$@"; }

sudo -n rm -rf "$SBS_SCRATCH"; mkdir -p "$SBS_SCRATCH/library"
sudo -n cp -a "$proj/data" "$SBS_SCRATCH/data" && sudo -n chown -R 65056:65056 "$SBS_SCRATCH/data" && sudo -n chmod 750 "$SBS_SCRATCH/data"
sudo -n chown 65056:1100 "$SBS_SCRATCH/library" && sudo -n chmod 2775 "$SBS_SCRATCH/library"
compose up -d --quiet-pull 2>&1 | grep -E 'Creat|Start|Error|error' | head -5
for i in $(seq 40); do
  st=$(docker inspect -f '{{.State.Health.Status}}' audiobook-importer-sbs 2>/dev/null); [[ $st == healthy ]] && break; sleep 1
done
ip=$(docker inspect -f '{{(index .NetworkSettings.Networks "audiobook-requests_egress").IPAddress}}' audiobook-importer-sbs)
echo "new: $ip health=$st image=$IMPORTER_IMAGE"

fail=0
same() { # same <name> <old> <new>
  if [[ "$2" == "$3" ]]; then echo "same  $1"; else echo "DIFF  $1"; echo "  old: ${2:0:300}"; echo "  new: ${3:0:300}"; fail=1; fi
}
old() { docker exec books-proxy wget -q -O - -T 20 --header "X-authentik-username: ${2:-sbs-nobody}" "http://audiobook-importer:8000$1" 2>/dev/null; }
new() { curl -s -m 20 -H "X-authentik-username: ${2:-sbs-nobody}" "http://$ip:8000$1"; }
norm() { python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps(d, sort_keys=True))' 2>/dev/null; }

same health "$(docker exec books-proxy wget -q -O - http://audiobook-importer:8000/health)" "$(new /health)"
same "my-quota (no user)" "$(docker exec books-proxy wget -q -S -O - http://audiobook-importer:8000/my-quota 2>&1 | grep -o 'HTTP/1.[01] [0-9]*' | awk 'NR==1{print $2}')" "$(curl -s -o /dev/null -w '%{http_code}' "http://$ip:8000/my-quota")"
same "library (unknown viewer)" "$(old /library | norm)" "$(new /library | norm)"
same "sizes (unknown viewer)" "$(old /sizes | norm)" "$(new /sizes | norm)"
same "all-requests (unknown viewer, sizes null)" "$(old /all-requests | norm)" "$(new /all-requests | norm)"
owner=$(docker exec books-proxy wget -q -O - http://audiobook-importer:8000/all-requests 2>/dev/null | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(rows[0]["requested_by"] if rows else "")' 2>/dev/null)
if [[ -n $owner ]]; then
  same "library (a real viewer)" "$(old /library "$owner" | norm)" "$(new /library "$owner" | norm)"
  same "sizes (a real viewer)" "$(old /sizes "$owner" | norm)" "$(new /sizes "$owner" | norm)"
  same "all-requests (a real viewer)" "$(old /all-requests "$owner" | norm)" "$(new /all-requests "$owner" | norm)"
  same "my-quota (a real viewer)" "$(old /my-quota "$owner" | norm)" "$(new /my-quota "$owner" | norm)"
fi
same "abs pass-through status (no key)" "$(curl -s -o /dev/null -w '%{http_code}' http://10.24.25.5:8000/abs/api/libraries)" "$(curl -s -o /dev/null -w '%{http_code}' "http://$ip:8000/abs/api/libraries")"
same "abs POST gate" "$(curl -s -o /dev/null -w '%{http_code}' -X POST http://10.24.25.5:8000/abs/api/libraries/x/scan)" "$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://$ip:8000/abs/api/libraries/x/scan")"
same "webhook from a stranger" "$(curl -s -o /dev/null -w '%{http_code}' -X POST -d '{}' http://10.24.25.5:8000/abr)" "$(curl -s -o /dev/null -w '%{http_code}' -X POST -d '{}' "http://$ip:8000/abr")"
same "ledger unchanged" "$(sudo -n cat "$proj/data/quota.json" | norm)" "$(sudo -n cat "$SBS_SCRATCH/data/quota.json" | norm)"
same "jobs unchanged" "$(sudo -n cat "$proj/data/jobs.json" | norm)" "$(sudo -n cat "$SBS_SCRATCH/data/jobs.json" | norm)"
echo "--- new container: $(docker stats --no-stream --format 'cpu={{.CPUPerc}} mem={{.MemUsage}} pids={{.PIDs}}' audiobook-importer-sbs)"
docker logs audiobook-importer-sbs 2>&1 | grep -v -E 'qBittorrent|10\.24\.25\.2' | tail -5
if [[ ${SBS_KEEP:-0} != 1 ]]; then compose down 2>&1 | grep -E 'Remov|Error|error' | head -3; fi
(( fail == 0 )) && echo "SIDE-BY-SIDE OK" || echo "SIDE-BY-SIDE DIFFERENCES"
exit $fail
