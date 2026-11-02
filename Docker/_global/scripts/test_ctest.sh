#!/usr/bin/env bash
# Runs ctest.sh against a fake docker. Usage: scripts/test_ctest.sh
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1 ${2:-}"; }
has()  { grep -q -x -- "$2" "$3" && ok "$1" || bad "$1" "no [$2]"; }
hasnt() { grep -q -- "$2" "$3" && bad "$1" "unexpected [$2]" || ok "$1"; }

cat > "$T/docker" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$@" >> "$FAKE_LOG"
[[ $1 == run && -n $FAKE_SLEEP ]] && sleep "$FAKE_SLEEP"
exit "${FAKE_RC:-0}"
STUB
chmod +x "$T/docker"
mkdir -p "$T/root/proj/tests" "$T/outside"
ln -s "$T/outside" "$T/root/proj/escape"
export FAKE_LOG="$T/log" PATH="$T:$PATH" CTEST_ROOTS="$T/root"
S="$HERE/ctest.sh"
run() { : > "$T/log"; "$S" "$@" >"$T/out" 2>&1; }

run -v "$T/root/proj:/work" -w /work --entrypoint promtool prom/prometheus:v3.15.1 test rules tests/a.yml
rc=$?
[[ $rc == 0 ]] && ok "valid run exits 0" || bad "valid run exits 0" "rc=$rc $(cat "$T/out")"
has "uses docker run" "run" "$T/log"
has "removes the container" "--rm" "$T/log"
has "no network" "--network=none" "$T/log"
has "read-only root fs" "--read-only" "$T/log"
has "drops all caps" "--cap-drop=ALL" "$T/log"
has "no new privileges" "--security-opt=no-new-privileges" "$T/log"
has "never pulls" "--pull=never" "$T/log"
has "runs as nobody" "--user=65534:65534" "$T/log"
has "tmpfs /tmp has a size limit" "--tmpfs=/tmp:rw,size=256m" "$T/log"
has "mount is read-only" "--mount=type=bind,src=$T/root/proj,dst=/work,readonly" "$T/log"
has "workdir passed" "--workdir=/work" "$T/log"
has "entrypoint passed" "--entrypoint=promtool" "$T/log"
has "image passed" "prom/prometheus:v3.15.1" "$T/log"
has "command passed after image" "tests/a.yml" "$T/log"
hasnt "never privileged" "privileged" "$T/log"

run -v "$T/root/proj/tests" alpine:3.20 ls
has "mount defaults to same path" "--mount=type=bind,src=$T/root/proj/tests,dst=$T/root/proj/tests,readonly" "$T/log"

run -e FOO=bar alpine:3.20 env
has "env passed" "--env=FOO=bar" "$T/log"

refuse() { local name=$1; shift; run "$@"; local rc=$?
  [[ $rc != 0 ]] && ! grep -q '^run$' "$T/log" && ok "$name" || bad "$name" "rc=$rc log=$(tr '\n' ' ' < "$T/log")"; }
refuse "mount outside the roots refused" -v "$T/outside:/x" alpine:3.20 ls
refuse "symlink escaping the roots refused" -v "$T/root/proj/escape:/x" alpine:3.20 ls
refuse "docker socket refused" -v /var/run/docker.sock:/s alpine:3.20 ls
refuse "relative container path refused" -v "$T/root/proj:work" alpine:3.20 ls
refuse "comma in container path refused" -v "$T/root/proj:/w,readonly=false" alpine:3.20 ls
refuse "unknown option refused" --privileged alpine:3.20 ls
refuse "option-looking image refused" --network=host
refuse "bad env name refused" -e "A B=1" alpine:3.20 env
refuse "missing image refused"
refuse "user option refused" -u 0 alpine:3.20 id
refuse "option-looking entrypoint refused" --entrypoint --privileged alpine:3.20

: > "$T/log"; FAKE_RC=3 "$S" alpine:3.20 false >/dev/null 2>&1; rc=$?
[[ $rc == 3 ]] && ok "container exit code passed through" || bad "container exit code passed through" "rc=$rc"

: > "$T/log"; FAKE_SLEEP=5 CTEST_TIMEOUT=1 "$S" alpine:3.20 sleep 9 >/dev/null 2>&1; rc=$?
[[ $rc == 124 ]] && ok "timeout exits 124" || bad "timeout exits 124" "rc=$rc"
has "timeout kills the container" "kill" "$T/log"

echo "$PASS passed, $FAIL failed"
[[ $FAIL == 0 ]]
