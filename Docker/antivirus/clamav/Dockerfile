FROM alpine:latest

RUN apk add --no-cache clamav clamav-daemon clamav-clamdscan clamav-libs freshclam netcat-openbsd

RUN mkdir -p /var/lib/clamav /run/clamav && \
    chown -R clamav:clamav /var/lib/clamav /run/clamav

COPY clamd.conf /etc/clamav/clamd.conf
COPY freshclam.conf /etc/clamav/freshclam.conf
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh && \
    chown clamav:clamav /etc/clamav/clamd.conf /etc/clamav/freshclam.conf

EXPOSE 3310

VOLUME /var/lib/clamav

HEALTHCHECK --interval=60s --timeout=10s --retries=3 --start-period=120s \
  CMD echo PING | nc -w3 127.0.0.1 3310 | grep -q PONG

ENTRYPOINT ["/entrypoint.sh"]
