#!/bin/sh
# Inside the Traefik image (run.sh): start Traefik on the internal entry point with the activity routes, then probe them.
sed 's#172.24.255.10/32#127.0.0.1/32#' /dyn/activity-internal.yml > /tmp/dyn.yml
traefik --entrypoints.internal.address=127.0.0.1:8080 --providers.file.filename=/tmp/dyn.yml --log.level=ERROR --accesslog=false >/tmp/traefik.log 2>&1 &
i=0
until wget -q -T 1 -O /dev/null --header 'Host: traefik' http://127.0.0.1:8080/x 2>/dev/null || wget -S -T 1 -O /dev/null --header 'Host: traefik' http://127.0.0.1:8080/x 2>&1 | grep -q 'HTTP/'; do
  i=$((i + 1)); [ $i -gt 50 ] && { echo "traefik did not start"; cat /tmp/traefik.log; exit 1; }; sleep 0.2
done
sleep 1
fail=0
probe() { # want method path
  if [ "$2" = POST ]; then code=$(wget -S -T 3 -O /dev/null --header 'Host: traefik' --post-data x "http://127.0.0.1:8080$3" 2>&1 | sed -n 's/.*HTTP\/1.1 \([0-9]*\).*/\1/p' | head -1)
  else code=$(wget -S -T 3 -O /dev/null --header 'Host: traefik' "http://127.0.0.1:8080$3" 2>&1 | sed -n 's/.*HTTP\/1.1 \([0-9]*\).*/\1/p' | head -1); fi
  if [ "$code" = "$1" ]; then echo "ok   $1 $2 $3"; else echo "FAIL want $1 got ${code:-none}: $2 $3"; fail=1; fi
}
probe 502 GET  '/activity/waker/status'
probe 502 GET  '/activity/gate/seerr/night-waiting.json'
probe 502 GET  '/activity/qbit/api/v2/torrents/info?category=abr'
probe 404 GET  '/activity/qbit/api/v2/torrents/info'
probe 404 GET  '/activity/qbit/api/v2/torrents/info?category=abr&category=books'
probe 404 GET  '/activity/qbit/api/v2/torrents/info?category=books&category=abr'
probe 404 GET  '/activity/qbit/api/v2/torrents/info?category=abr&category='
probe 404 GET  '/activity/qbit/api/v2/torrents/info?category=ABR'
probe 404 GET  '/activity/qbit/api/v2/torrents/info?category=abr%0A'
probe 404 GET  '/activity/qbit/api/v2/torrents/info?category=abrx'
probe 404 GET  '/activity/qbit/api/v2/torrents/info?cat%65gory=books&category=abr'
for p in filter tag sort reverse limit offset hashes private includeTrackers include_trackers includeFiles; do
  probe 404 GET "/activity/qbit/api/v2/torrents/info?category=abr&$p=x"
done
probe 404 GET  '/activity/qbit/api/v2/torrents/properties?category=abr'
probe 404 POST '/activity/qbit/api/v2/torrents/info?category=abr'
if grep -qi 'error' /tmp/traefik.log; then echo "FAIL traefik log:"; cat /tmp/traefik.log; fail=1; fi
[ $fail = 0 ] && echo "all routes as expected"
exit $fail
