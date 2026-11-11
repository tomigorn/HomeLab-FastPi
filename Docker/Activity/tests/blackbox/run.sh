#!/usr/bin/env bash
# Black-box suite in a network-less throwaway container (ctest.sh): fakes for the Waker, the activity-gate, Audiobookshelf and qBittorrent on loopback.
#   run.sh                 the binary inside activity:local
#   run.sh image IMAGE     the binary inside IMAGE (weekly rebuild: rebuild-local.conf `test`)
#   run.sh bin BINARY      a binary on disk (under the project dir)
#   extra args after that go to unittest, e.g. run.sh bin rust/target-out/activity Asleep
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
proj=$(cd "$here/../.." && pwd)
image=${BLACKBOX_IMAGE:-python:3.13-alpine}
mode=${1:-image}; shift || true
case $mode in
  image|bin)
    if [[ $mode == bin ]]; then bin=$(realpath "${1:?binary}"); shift; chmod 755 "$(dirname "$bin")"; else
      img=${1:-activity:local}; (($#)) && shift
      bin=$proj/rust/target-out/activity
      mkdir -p "$(dirname "$bin")"; chmod 755 "$(dirname "$bin")"
      cid=$(docker create "$img")
      docker cp "$cid:/activity" "$bin" >/dev/null; docker rm "$cid" >/dev/null
    fi ;;
  *) echo "usage: run.sh [image IMAGE | bin BINARY] [unittest args]" >&2; exit 2 ;;
esac
tests=(test_blackbox); (($#)) && tests=("${@/#/test_blackbox.}")
CTEST_TIMEOUT=${CTEST_TIMEOUT:-600} exec bash /usr/local/libexec/fastpi/ctest.sh -v "$here:/tests" -v "$proj/rust/fixtures:/fixtures" \
  -v "$(dirname "$bin"):/sut" -e "SUT=/sut/$(basename "$bin")" -e PYTHONDONTWRITEBYTECODE=1 -w /tests \
  --entrypoint python "$image" -m unittest -v "${tests[@]}"
