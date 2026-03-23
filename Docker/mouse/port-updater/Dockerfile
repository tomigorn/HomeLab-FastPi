FROM alpine:3.19
# include tzdata so named timezones from TZ work inside the container
RUN apk add --no-cache curl docker-cli tzdata python3
COPY port-updater.sh /usr/local/bin/port-updater.sh
COPY web-server.py   /usr/local/bin/web-server.py
COPY entrypoint.sh   /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/port-updater.sh
EXPOSE 8088
CMD ["/usr/local/bin/entrypoint.sh"]
