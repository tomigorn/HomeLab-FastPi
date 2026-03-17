FROM alpine:3.19
RUN apk add --no-cache curl docker-cli
COPY port-updater.sh /usr/local/bin/port-updater.sh
CMD ["sh", "/usr/local/bin/port-updater.sh"]
