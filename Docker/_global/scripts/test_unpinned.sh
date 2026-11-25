#!/usr/bin/env bash
# Feeds fake `docker inspect` JSON to unpinned.sh. Usage: scripts/test_unpinned.sh
HERE=$(cd "$(dirname "$0")" && pwd)
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }
eq()  { [[ $2 == "$3" ]] && ok "$1" || bad "$1" "got [$2] want [$3]"; }

pinned='{"Name":"/a","HostConfig":{"NetworkMode":"web"},"NetworkSettings":{"Networks":{"web":{"IPAMConfig":{"IPv4Address":"172.20.0.5"}}}}}'
loose='{"Name":"/dash","HostConfig":{"NetworkMode":"web"},"NetworkSettings":{"Networks":{"web":{"IPAMConfig":null},"db":{"IPAMConfig":{"IPv4Address":"172.21.0.2"}}}}}'
loose2='{"Name":"/jf","HostConfig":{"NetworkMode":"media"},"NetworkSettings":{"Networks":{"media":{"IPAMConfig":{"IPv4Address":""}}}}}'
host='{"Name":"/h","HostConfig":{"NetworkMode":"host"},"NetworkSettings":{"Networks":{"host":{"IPAMConfig":null}}}}'
none='{"Name":"/n","HostConfig":{"NetworkMode":"none"},"NetworkSettings":{"Networks":{"none":{"IPAMConfig":null}}}}'
joined='{"Name":"/j","HostConfig":{"NetworkMode":"container:abc"},"NetworkSettings":{"Networks":{}}}'
svc='{"Name":"/s","HostConfig":{"NetworkMode":"service:x"},"NetworkSettings":{"Networks":{"service:x":{"IPAMConfig":null}}}}'
run() { printf '[%s]' "$1" | bash "$HERE/unpinned.sh"; }

eq "all pinned -> empty"            "$(run "$pinned,$host,$none,$joined,$svc")" ""
eq "null IPAMConfig listed"         "$(run "$pinned,$loose")" "dash/web"
eq "empty IPv4Address listed"       "$(run "$loose2")" "jf/media"
eq "host/none/container/service skipped" "$(run "$host,$none,$joined,$svc")" ""
eq "several joined on one line"     "$(run "$loose,$loose2")" "dash/web jf/media"
echo "PASS $PASS FAIL $FAIL"; (( FAIL == 0 ))
