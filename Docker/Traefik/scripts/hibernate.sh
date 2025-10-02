#!/usr/bin/env bash
# example script that hibernates a linux host via SSH
# usage: ./hibernate.sh buntu@beefy


TARGET=$1
KEY=$2
HIBER_PASS=$3
if [ -z "$TARGET" ] || [ -z "$KEY" ]; then
echo "usage: $0 user@host /path/to/key"
exit 2
fi
ssh -i "$KEY" -o BatchMode=yes "$TARGET" "printf '%s' \"$HIBER_PASS\" | sudo -S systemctl hibernate"