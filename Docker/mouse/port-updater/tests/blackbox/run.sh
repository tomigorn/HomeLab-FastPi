#!/usr/bin/env bash
# Black-box suite against the legacy shell/Python image or the Rust image, inside ctest.sh (no network, read-only).
# Usage: run.sh legacy|rust [IMAGE] [HISTORY_FIXTURE]
#   legacy: builds legacy/ (or uses IMAGE); rust: IMAGE defaults to mouse-port-updater:latest
# BUILD_LOCK: flock file serialising image builds (default ~/.cache/rust-build.lock). SCRIPT=bench.py runs the benchmark instead. Test names after -- are passed to unittest, e.g. run.sh rust "" "" -- Web
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
src=$(cd "$here/../.." && pwd)
cfg=$(cd "$src/../../Docker-Socket-Proxy" && pwd)/portupdater-haproxy.cfg
target=${1:?legacy|rust}; image=${2:-}; fixture=${3:-}
shift $(( $# < 3 ? $# : 3 )); [[ ${1:-} == -- ]] && shift
extra_page=()
lock=${BUILD_LOCK:-$HOME/.cache/rust-build.lock}; mkdir -p "$(dirname "$lock")"
case $target in
  legacy)
    if [[ -z $image ]]; then image=port-updater-legacy:blackbox; flock "$lock" docker build -q -t "$image" "$src/legacy" >/dev/null; fi
    printf 'FROM %s\nUSER root\nRUN rm -rf /data && ln -s /tmp/data /data\n' "$image" | flock "$lock" docker build -q -t port-updater-blackbox:legacy - >/dev/null
    sut=/usr/local/bin/entrypoint.sh ;;
  rust)
    image=${image:-mouse-port-updater:latest}
    printf 'FROM %s AS bin\nFROM python:3.13-alpine\nCOPY --from=bin /port-updater /usr/local/bin/port-updater\nRUN ln -s /tmp/data /data\n' "$image" | flock "$lock" docker build -q -t port-updater-blackbox:rust - >/dev/null
    sut=/usr/local/bin/port-updater; extra_page=(-e PAGE_FILE=/src/src/index.html) ;;
  *) echo "usage: $0 legacy|rust [IMAGE] [HISTORY_FIXTURE]" >&2; exit 2 ;;
esac
extra=("${extra_page[@]}")
[[ -n $fixture ]] && extra+=(-v "$(realpath "$fixture"):/fixture.json" -e HISTORY_FIXTURE=/fixture.json)
CTEST_TIMEOUT=900 bash /usr/local/libexec/fastpi/ctest.sh -v "$src:/src" -v "$cfg:/haproxy.cfg" -w /src/tests/blackbox \
  -e SUT_CMD="$sut" -e PYTHONDONTWRITEBYTECODE=1 -e LEGACY_WEB=/src/legacy/web-server.py "${extra[@]}" \
  --entrypoint python3 "port-updater-blackbox:$target" "${SCRIPT:-test_blackbox.py}" "$@"
