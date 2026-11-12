#!/usr/bin/env bash
# The internal routes of ../../../Traefik/traefik/dynamic/activity-internal.yml in a real Traefik (ctest.sh: no network, read-only).
# The allow-list address becomes 127.0.0.1; backends are unreachable, so a request the rule lets through answers 502, one it refuses 404.
#   run.sh [TRAEFIK_IMAGE]   default: the image of the running traefik container
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
dyn=$(realpath "$here/../../../Traefik/traefik/dynamic")
image=${1:-$(docker inspect -f '{{.Config.Image}}' traefik)}
exec bash /usr/local/libexec/fastpi/ctest.sh -v "$dyn:/dyn" -v "$here:/t" --entrypoint sh "$image" /t/routes.sh
