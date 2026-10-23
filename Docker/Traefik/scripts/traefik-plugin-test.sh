#!/usr/bin/env bash
# traefik-plugin-test.sh <traefik tag>   e.g. v3.7.17
# Starts that Traefik version in a throwaway container on its own network (no host ports) with the repo's
# local plugins and dynamic config (adapted), a whoami echo backend and a mock CrowdSec LAPI, checks
# realip + crowdsec-bouncer work, tears everything down. Exit 0 only if every check passes.
set -uo pipefail
tag=${1:-}
[[ $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "usage: $0 vX.Y.Z"; exit 2; }
WHOAMI=traefik/whoami:v1.11.0
CADDY=caddy:2.11.7-alpine
CURL=curlimages/curl:8.23.0
BANNED4=198.51.100.66 BANNED6=2001:db8::66 CLEAN4=203.0.113.7 CLEAN6=2001:db8::7 KEY=plugin-test-dummy-key
repo=$(cd "$(dirname "$0")/.." && pwd)
id=traefik-plugin-test-$$
tmp=$(mktemp -d)
PASS=0; FAIL=0
ok()  { printf '  PASS %-38s %s\n' "$1" "${2:0:80}"; PASS=$((PASS+1)); }
bad() { printf '  FAIL %-38s %s\n' "$1" "${2:-}"; FAIL=$((FAIL+1)); }
check() { if [[ $3 =~ $2 ]]; then ok "$1" "$3"; else bad "$1" "got: $3"; fi; }
cleanup() { docker rm -f "$id-traefik" "$id-whoami" "$id-lapi" >/dev/null 2>&1; docker network rm "$id" >/dev/null 2>&1; rm -rf "$tmp"; }
trap cleanup EXIT
harden=(--user 65026:65026 --cap-drop ALL --security-opt no-new-privileges:true --read-only --tmpfs /tmp --memory 256m)

echo "== Traefik $tag plugin test"
docker image inspect "traefik:$tag" >/dev/null 2>&1 || docker pull -q "traefik:$tag" >/dev/null || { echo "FAIL cannot pull traefik:$tag"; exit 1; }
docker network create "$id" >/dev/null || exit 1
gw=$(docker network inspect -f '{{(index .IPAM.Config 0).Gateway}}' "$id")
[[ $gw =~ ^[0-9.]+$ ]] || { echo "FAIL no gateway on test network"; exit 1; }

mkdir -p "$tmp/dynamic" "$tmp/secrets"
mws=$(awk '/^  websecure:/{f=1;next} /^  [a-z]+:$/{f=0} f&&/^ *- [a-z-]+@file/{print "        - "$2}' "$repo/traefik/traefik.yml")
{
  printf 'entryPoints:\n  test:\n    address: ":8000"\n    http:\n      middlewares:\n%s\n    forwardedHeaders:\n      trustedIPs:\n        - "%s/32"\n' "$mws" "$gw"
  printf 'log:\n  level: DEBUG\n  noColor: true\nproviders:\n  file:\n    directory: /dynamic\n'
  sed -n '/^experimental:/,$p' "$repo/traefik/traefik.yml"
} > "$tmp/traefik.yml"
sed "s|172.24.0.1/32|$gw/32|" "$repo/traefik/dynamic/real-ip.yml" > "$tmp/dynamic/real-ip.yml"
sed -e "s|172.24.0.1/32|$gw/32|" -e "s|crowdsecLapiHost: .*|crowdsecLapiHost: $id-lapi:8080|" "$repo/traefik/dynamic/crowdsec.yml" > "$tmp/dynamic/crowdsec.yml"
cat > "$tmp/dynamic/router.yml" <<EOF
http:
  routers:
    test:
      entryPoints: [test]
      rule: PathPrefix(\`/\`)
      service: whoami
  services:
    whoami:
      loadBalancer:
        servers:
          - url: http://$id-whoami:8080
EOF
printf '%s' "$KEY" > "$tmp/secrets/crowdsec_lapi_key"
d='"duration":"1h","origin":"cscli","scenario":"plugin-test","scope":"Ip","type":"ban"'
cat > "$tmp/Caddyfile" <<EOF
{
	admin off
}
:8080 {
	@nokey not header X-Api-Key $KEY
	respond @nokey 403
	header Content-Type application/json
	respond /v1/decisions/stream* \`{"new":[{"id":1,$d,"value":"$BANNED4"},{"id":2,$d,"value":"$BANNED6"}],"deleted":null}\` 200
	respond 200
}
EOF
chmod -R a+rX "$tmp"
grep -q "$gw/32" "$tmp/dynamic/real-ip.yml" && grep -q "$gw/32" "$tmp/dynamic/crowdsec.yml" && grep -q "crowdsecLapiHost: $id-lapi:8080" "$tmp/dynamic/crowdsec.yml" && [[ -n $mws ]] \
  || { echo "FAIL could not adapt the repo config (traefik.yml / real-ip.yml / crowdsec.yml changed shape?)"; exit 1; }

docker run -d --name "$id-whoami" --network "$id" "${harden[@]}" "$WHOAMI" --port 8080 >/dev/null || exit 1
docker run -d --name "$id-lapi" --network "$id" "${harden[@]}" --cap-add NET_BIND_SERVICE -e XDG_CONFIG_HOME=/tmp -e XDG_DATA_HOME=/tmp \
  -v "$tmp/Caddyfile:/etc/caddy/Caddyfile:ro" "$CADDY" >/dev/null || exit 1
docker run -d --name "$id-traefik" --network "$id" "${harden[@]}" \
  -v "$tmp/traefik.yml:/etc/traefik/traefik.yml:ro" -v "$tmp/dynamic:/dynamic:ro" -v "$tmp/secrets:/secrets:ro" \
  -v "$repo/traefik/plugins-local:/plugins-local:ro" "traefik:$tag" >/dev/null || exit 1
tip=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$id\").IPAddress}}" "$id-traefik")

url=http://$tip:8000/
req() { curl -s -m 5 -o /dev/null -w '%{http_code}' -H "Cf-Connecting-Ip: $1" "$url"; }
for _ in $(seq 30); do [[ $(req "$CLEAN4") == 200 && $(req "$BANNED4") == 403 ]] && break; sleep 1; done
log=$(docker logs "$id-traefik" 2>&1)

check "traefik version"                "^${tag#v}$" "$(docker exec "$id-traefik" traefik version 2>/dev/null | awk '/Version:/{print $2}')"
check "plugins loaded"                 'realip.*crowdsec-bouncer|crowdsec-bouncer.*realip' "$(grep -m1 'Plugins loaded' <<<"$log" | grep -o 'plugins=.*' || echo none)"
check "no error in log"                '^0$' "$(grep -cE ' (ERR|FTL) |level=ERROR' <<<"$log")"
check "realip+crowdsec on entrypoint"  '^real-ip@file crowdsec@file$' "$(echo $mws | sed 's/- //g')"
# Traefik's proxy appends the connection address after the middlewares, so the backend sees "<client>, <conn addr>".
echo_of() { curl -s -m 5 "${@}" "$url" | tr -d '\r' | grep -iE '^X-(Forwarded-For|Real-Ip):' | sort | tr '\n' ' ' | sed 's/ $//'; }
check "tunnel IPv4: XFF = Cf-Connecting-Ip" "^X-Forwarded-For: $CLEAN4, $gw X-Real-Ip: $CLEAN4$" "$(echo_of -H "Cf-Connecting-Ip: $CLEAN4" -H 'X-Forwarded-For: 6.6.6.6')"
check "tunnel IPv6: XFF = Cf-Connecting-Ip" "^X-Forwarded-For: $CLEAN6, $gw X-Real-Ip: $CLEAN6$" "$(echo_of -H "Cf-Connecting-Ip: $CLEAN6")"
other=$(docker run --rm --network "$id" "${harden[@]}" "$CURL" \
  sh -c "hostname -i; curl -s -m 5 -H 'Cf-Connecting-Ip: $BANNED4' -H 'X-Forwarded-For: 6.6.6.6' http://$tip:8000/" | tr -d '\r')
oip=$(head -1 <<<"$other" | awk '{print $1}')
check "other source: XFF = own IP"     "^X-Forwarded-For: $oip, $oip X-Real-Ip: $oip$" "$(grep -iE '^X-(Forwarded-For|Real-Ip):' <<<"$other" | sort | tr '\n' ' ' | sed 's/ $//')"
# The mock LAPI answers 403 without the key file's key, so these bans also prove crowdsecLapiKeyFile is read.
check "crowdsec: banned IPv4 -> 403"   '^403$' "$(req "$BANNED4")"
check "crowdsec: banned IPv6 -> 403"   '^403$' "$(req "$BANNED6")"
check "crowdsec: clean IPv4 -> 200"    '^200$' "$(req "$CLEAN4")"
check "crowdsec: clean IPv6 -> 200"    '^200$' "$(req "$CLEAN6")"

echo "PASS $PASS   FAIL $FAIL"
(( FAIL == 0 ))
