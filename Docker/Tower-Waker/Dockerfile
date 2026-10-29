FROM python:3.13-alpine
# openssh-client is carried over from Beefy-Waker, where /history fetches the
# boot list over a locked-down read-only forced-command SSH key. It is UNUSED on
# tower: Unraid is not systemd and has no journal, so /history cannot work and the
# compose file mounts no key. Kept only to keep the two images identical; drop it
# together with the /history code if the wakers are ever split for good.
# A real user with the compose uid (65006) is needed so the ssh client has a passwd entry (it refuses
# to run as an unknown uid: "No user exists for uid") — it also matches the host-owned app mounts.
# pip is removed: the app is stdlib only, and pip's vendored urllib3/msgpack/setuptools were the image's only HIGH CVEs.
RUN apk add --no-cache openssh-client \
 && addgroup -g 65006 waker \
 && adduser -D -u 65006 -G waker waker \
 && python -m pip uninstall -y -q pip \
 && rm -rf /usr/local/lib/python3.13/ensurepip /root/.cache
