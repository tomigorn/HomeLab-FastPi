#!/usr/bin/env bash
# Black-box suite against an image: run.sh [IMAGE] [TEST-NAME-FILTER...]; the watcher command is the image's entrypoint.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
image=${1:-m4b-auto-merge:local}; shift || true
script=test_blackbox.py; [[ -n ${BENCH:-} ]] && script=bench.py
watcher=$(docker image inspect -f '{{join .Config.Entrypoint " "}}' "$image")
CTEST_TIMEOUT=${CTEST_TIMEOUT:-600} exec bash /usr/local/libexec/fastpi/ctest.sh -v "$here:/t" -w /t -e "WATCHER=$watcher" \
  -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python3 "$image" "/t/$script" "$@"
