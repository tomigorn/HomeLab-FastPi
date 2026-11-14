# Tower waker customizations (Docker/CUSTOMIZATIONS.md "Tower-Waker"). Never wakes tower: every request here is refused or read-only.
if want waker; then
  check tower-waker.status '"up": (true|false), "waited_seconds": ' "$(curl -s -m 5 http://192.168.1.2:9002/status)"
  check tower-waker.version '^same$' "$(v=$(curl -s -m 5 http://192.168.1.2:9002/nc | grep -oE 'tower-waker [0-9]+\.[0-9]+\.[0-9]+' | cut -d' ' -f2); [[ $v == "$(cat "$(dirname "${BASH_SOURCE[0]}")/../../Tower-Waker/app/VERSION")" ]] && echo same || echo "page ${v:-none}")"
  check tower-waker.wake-csrf '^403 403$' "$(u=http://192.168.1.2:9002/wake; echo "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST $u) $(curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST -H 'X-Wake: 1' -H 'Origin: https://evil.example.com' $u)")"   # D-11
fi
