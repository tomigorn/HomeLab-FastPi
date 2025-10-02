#!/usr/bin/env bash
# Enhanced hibernation script with logging
# Usage: ./hibernate.sh [user@host] [optional-check-command]

set -e

TARGET=${1:-"buntu@192.168.1.102"}
CHECK_CMD=${2:-"docker ps -q | wc -l"}

echo "$(date): Preparing to hibernate $TARGET"

# Check if there are active containers or processes
ACTIVE_COUNT=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "$TARGET" "$CHECK_CMD" 2>/dev/null || echo "0")

if [ "$ACTIVE_COUNT" -gt 0 ]; then
    echo "$(date): Server has $ACTIVE_COUNT active processes/containers. Skipping hibernation."
    exit 0
fi

echo "$(date): Server appears idle. Proceeding with hibernation..."

# Hibernate the server
if ssh -o BatchMode=yes -o ConnectTimeout=5 "$TARGET" 'sudo systemctl hibernate' 2>/dev/null; then
    echo "$(date): Successfully sent hibernation command to $TARGET"
else
    echo "$(date): Failed to hibernate $TARGET" >&2
    exit 1
fi
