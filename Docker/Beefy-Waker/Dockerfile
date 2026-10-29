FROM python:3.13-alpine@sha256:8bcfa47b04b853a17aaf909362b847b2112fd6ec4105ea553ef9a43bafbb5916
# openssh-client: the /history endpoint fetches beefy's boot list over a
# locked-down, read-only forced-command SSH key (journalctl --list-boots only).
# A real user with the compose uid (65005) is needed so the ssh client has a passwd entry (it refuses
# to run as an unknown uid: "No user exists for uid") — it also matches the host-owned key/app mounts.
# pip is removed: the app is stdlib only, and pip's vendored urllib3/msgpack/setuptools were the image's only HIGH CVEs.
RUN apk add --no-cache openssh-client \
 && addgroup -g 65005 waker \
 && adduser -D -u 65005 -G waker waker \
 && python -m pip uninstall -y -q pip \
 && rm -rf /usr/local/lib/python3.13/ensurepip /root/.cache
