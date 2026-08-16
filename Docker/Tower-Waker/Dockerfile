FROM python:3.13-alpine
# openssh-client is carried over from Beefy-Waker, where /history fetches the
# boot list over a locked-down read-only forced-command SSH key. It is UNUSED on
# tower: Unraid is not systemd and has no journal, so /history cannot work and the
# compose file mounts no key. Kept only to keep the two images identical; drop it
# together with the /history code if the wakers are ever split for good.
# A real uid-1000 user is needed so the ssh client has a passwd entry (it refuses
# to run as an unknown uid) — uid/gid 1000 also matches the host-owned app mounts.
RUN apk add --no-cache openssh-client \
 && addgroup -g 1000 waker \
 && adduser -D -u 1000 -G waker waker
