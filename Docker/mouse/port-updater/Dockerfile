FROM alpine:3.19
# include tzdata so named timezones from TZ work inside the container
RUN apk add --no-cache curl docker-cli tzdata
COPY port-updater.sh /usr/local/bin/port-updater.sh
CMD ["sh", "/usr/local/bin/port-updater.sh"]
