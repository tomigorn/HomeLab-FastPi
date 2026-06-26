FROM python:3.13-alpine
# openssh-client: the /history endpoint fetches beefy's boot list over a
# locked-down, read-only forced-command SSH key (journalctl --list-boots only).
# A real uid-1000 user is needed so the ssh client has a passwd entry (it refuses
# to run as an unknown uid) — uid/gid 1000 also matches the host-owned key/app mounts.
RUN apk add --no-cache openssh-client \
 && addgroup -g 1000 waker \
 && adduser -D -u 1000 -G waker waker
