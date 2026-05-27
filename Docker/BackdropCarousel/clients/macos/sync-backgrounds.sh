#!/bin/bash

REMOTE_URL="https://backdrop-carousel.holy-grail.ch"
LOCAL_DIR="$HOME/Pictures/BackdropCarousel"

mkdir -p "$LOCAL_DIR"

remote_photos=$(curl -sf "$REMOTE_URL/" | python3 -c "import sys,json; [print(p['name']) for p in json.load(sys.stdin)]") || exit 1

for name in $remote_photos; do
    if [ ! -f "$LOCAL_DIR/$name" ]; then
        curl -sf "$REMOTE_URL/photo/$name" -o "$LOCAL_DIR/$name"
    fi
done

for file in "$LOCAL_DIR"/*; do
    [ -f "$file" ] || continue
    name=$(basename "$file")
    if ! echo "$remote_photos" | grep -qxF "$name"; then
        rm "$file"
    fi
done
