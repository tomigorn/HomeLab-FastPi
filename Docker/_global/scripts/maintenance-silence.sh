#!/usr/bin/env bash
# Alertmanager silence for batch and upgrade work, so planned restarts, file changes and own logins do not page; the 06:30 daily digest still lists what fired.
# Usage: maintenance-silence.sh on [hours, default 4, max 24] [reason] | off | status
set -euo pipefail

DOCKER=${DOCKER:-docker}
AUTHOR=maintenance-silence
MATCHER='alertname=~"ContainerCrashLooping|ContainerDown|ContainerUnhealthy|SecurityFileChanged|HostRebooted|SshLoginOutsideLan"'

am() { "$DOCKER" exec alertmanager amtool --alertmanager.url=http://127.0.0.1:9093 "$@"; }

ours() {
    am silence query -o json | python3 -c '
import json, sys
for s in json.load(sys.stdin):
    if s.get("createdBy") == sys.argv[1] and s.get("status", {}).get("state") == "active":
        print(s["id"], s["endsAt"], s.get("comment", ""))' "$AUTHOR"
}

expire_ours() {
    local ids
    ids=$(ours | cut -d' ' -f1)
    [[ -z $ids ]] || am silence expire $ids
}

case "${1:-}" in
    on)
        hours=${2:-4}
        [[ $hours =~ ^[0-9]+$ ]] && (( hours >= 1 && hours <= 24 )) || { echo "hours must be 1-24" >&2; exit 2; }
        reason=${3:-batch work}
        expire_ours
        id=$(am silence add --author="$AUTHOR" --duration="${hours}h" --comment="maintenance: $reason" "$MATCHER")
        echo "maintenance silence $id for ${hours}h: $reason"
        ;;
    off)
        expire_ours
        echo "maintenance silence off"
        ;;
    status)
        ours
        ;;
    *)
        echo "usage: $0 on [hours] [reason] | off | status" >&2
        exit 2
        ;;
esac
