#!/usr/bin/env bash
# Black-box suite against an importer binary or script. No network: qBittorrent, ABS, ABR, Prowlarr and Audible are fakes on loopback.
#   bash run.sh                      current Python (IMPORTER_LEGACY=1: tests for known legacy bugs are skipped)
#   bash run.sh <command...>         e.g. bash run.sh ./audiobook-importer   (the Rust binary, AUDIBLE_MOCK=1 adds the Audible tests)
# Env: BLACKBOX_WORK (scratch dir, default ~/.cache/claude-work/importer-blackbox), BLACKBOX_KEEP=1 keeps the per-class folders.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
if (($#)); then
  export IMPORTER_CMD="$*"
  export AUDIBLE_MOCK=${AUDIBLE_MOCK:-1}
else
  export IMPORTER_LEGACY=1
fi
cd "$here" && exec python3 -m unittest discover -s . -p 'test_*.py' "${VERBOSE:+-v}"
