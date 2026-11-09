#!/usr/bin/env bash
# Black-box suite against the binary inside an image: bash run-image.sh [image] (default audiobook-importer:local).
# The static binary is copied out of a stopped container into ~/.cache/claude-work and run on the host against the fakes.
set -euo pipefail
image=${1:-audiobook-importer:local}
here=$(cd "$(dirname "$0")" && pwd)
work=${BLACKBOX_WORK:-$HOME/.cache/claude-work/importer-blackbox}
mkdir -p "$work"
bin="$work/audiobook-importer.$$"
cid=$(docker create --pull=never "$image")
trap 'docker rm -f "$cid" >/dev/null 2>&1; rm -f "$bin"' EXIT
docker cp "$cid:/audiobook-importer" "$bin" >/dev/null
chmod 0755 "$bin"
bash "$here/run.sh" "$bin"
