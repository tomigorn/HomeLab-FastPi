#!/usr/bin/env bash
# Black-box suite in a network-less throwaway container (ctest.sh).
#   run.sh old          the Python app in app/ (legacy)
#   run.sh new [BIN]    the Rust binary (default: copied out of tower-waker:local)
#   extra args after the mode go to unittest, e.g. run.sh new Pages StreamAuth
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
proj=$(cd "$here/../.." && pwd)
image=${BLACKBOX_IMAGE:-python:3.13-alpine}
mode=${1:-new}; shift || true
args=(-v "$proj/app:/app" -v "$here:/tests" -w /tests -e PYTHONDONTWRITEBYTECODE=1 -e VERSION_FILE=/app/VERSION)
case $mode in
  old) args+=(-e "SUT=python /app/waker.py") ;;
  new)
    bin=${1:-}
    if [[ -n $bin && -f $bin ]]; then shift; else
      bin=$proj/rust/target-out/tower-waker
      mkdir -p "$(dirname "$bin")"
      cid=$(docker create "${IMAGE:-tower-waker:local}")
      docker cp "$cid:/tower-waker" "$bin" >/dev/null; docker rm "$cid" >/dev/null
    fi
    args+=(-v "$(dirname "$(realpath "$bin")"):/sut" -e "SUT=/sut/$(basename "$bin")") ;;
  *) echo "usage: run.sh old|new [BIN] [unittest args]" >&2; exit 2 ;;
esac
tests=(test_blackbox); (($#)) && tests=("${@/#/test_blackbox.}")
CTEST_TIMEOUT=${CTEST_TIMEOUT:-900} exec bash /usr/local/libexec/fastpi/ctest.sh "${args[@]}" --entrypoint python "$image" -m unittest -v "${tests[@]}"
