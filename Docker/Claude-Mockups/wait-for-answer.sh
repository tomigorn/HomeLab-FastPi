#!/usr/bin/env bash
# Wait for a Claude-Mockups answer to arrive, then print it.
#
# Used by Claude: after deploying a question page (with a unique token), launch
# this in the BACKGROUND so the user's Confirm in the web UI wakes Claude — no
# returning to the terminal to retype the choice.
#
# Usage:  ./wait-for-answer.sh <token> [timeout-seconds]
#   exit 0 + "ANSWER ..."  -> a selection was received (JSON printed below)
#   exit 1 + "TIMEOUT ..."  -> nothing arrived within the timeout
set -euo pipefail

TOKEN="${1:?usage: wait-for-answer.sh <token> [timeout-seconds]}"
TIMEOUT="${2:-1800}"   # default 30 minutes

case "$TOKEN" in
  *[!A-Za-z0-9_-]*) echo "ERROR: token must match [A-Za-z0-9_-]" >&2; exit 2 ;;
esac

DIR="$(cd "$(dirname "$0")" && pwd)/answers"
F="$DIR/$TOKEN.json"

elapsed=0
while [ ! -f "$F" ]; do
  sleep 2
  elapsed=$((elapsed + 2))
  if [ "$elapsed" -ge "$TIMEOUT" ]; then
    echo "TIMEOUT: no answer for token '$TOKEN' after ${TIMEOUT}s"
    exit 1
  fi
done

echo "ANSWER for token '$TOKEN' (after ~${elapsed}s):"
cat "$F"
