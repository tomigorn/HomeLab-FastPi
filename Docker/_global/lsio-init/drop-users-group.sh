#!/usr/bin/with-contenv bash
# The linuxserver base image puts abc into "users", which is gid 1000 here (the host's pi group).
if id -nG abc | tr ' ' '\n' | grep -qx users; then
    gpasswd -d abc users >/dev/null
fi
