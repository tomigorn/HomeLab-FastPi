FROM alpine:latest

RUN apk add --no-cache clamav-scanner clamav-libs freshclam inotify-tools

RUN (addgroup -S clamav 2>/dev/null || true) && \
    (adduser -S -H -s /sbin/nologin -G clamav clamav 2>/dev/null || true) && \
    mkdir -p /var/lib/clamav /run/clamav && \
    chown -R clamav:clamav /var/lib/clamav /run/clamav

COPY freshclam.conf /etc/clamav/freshclam.conf
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh && \
    chown clamav:clamav /etc/clamav/freshclam.conf

VOLUME /var/lib/clamav

HEALTHCHECK --interval=60s --timeout=10s --retries=3 --start-period=120s \
  CMD pgrep inotifywait >/dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
