FROM python:3.13-alpine
# openssh-client: the /history endpoint fetches beefy's boot list over a
# locked-down, read-only forced-command SSH key (journalctl --list-boots only).
RUN apk add --no-cache openssh-client
