#!/usr/bin/env bash
# Usage: run.sh legacy | rust <binary> | url <url> <data-dir>
set -euo pipefail
umask 022   # the container default; the host has 002
cd "$(dirname "$0")/../.."
case "${1:-}" in
  legacy) exec python3 -I tests/blackbox/run.py --server-cmd "node legacy/server.js" ${RECORD:+--record "$RECORD"} ;;
  rust)   exec python3 -I tests/blackbox/run.py --server-cmd "${2:?binary}" ${RECORD:+--record "$RECORD"} ;;
  url)    exec python3 -I tests/blackbox/run.py --url "${2:?url}" --data "${3:?data dir}" ${RECORD:+--record "$RECORD"} ;;
  *) echo "usage: run.sh legacy | rust <binary> | url <url> <data-dir>" >&2; exit 2 ;;
esac
