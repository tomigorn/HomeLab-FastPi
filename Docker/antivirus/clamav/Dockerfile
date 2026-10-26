FROM alpine:latest

RUN apk add --no-cache clamav-scanner clamav-libs freshclam clamav-daemon clamav-clamdscan

# apk creates clamav as 100/101 (the host's messagebus); pin it to a dedicated uid/gid.
RUN deluser clamav 2>/dev/null; delgroup clamav 2>/dev/null; \
    addgroup -S -g 65039 clamav && \
    adduser -S -D -H -u 65039 -s /sbin/nologin -G clamav clamav && \
    mkdir -p /var/lib/clamav /run/clamav /var/log/clamav && \
    chown -R clamav:clamav /var/lib/clamav /run/clamav /var/log/clamav

COPY freshclam.conf /etc/clamav/freshclam.conf
COPY entrypoint.sh /entrypoint.sh
COPY scan.sh /scan.sh
COPY hostscan.sh /hostscan.sh

RUN chmod +x /entrypoint.sh /scan.sh /hostscan.sh && \
    chown clamav:clamav /etc/clamav/freshclam.conf

VOLUME /var/lib/clamav

USER clamav

HEALTHCHECK --interval=60s --timeout=10s --retries=3 --start-period=120s \
  CMD pgrep freshclam >/dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
