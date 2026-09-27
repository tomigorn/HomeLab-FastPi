FROM python:3.12-alpine

# openssh-client + rsync: the orchestrator ships each book to beefy over ssh.
# ffmpeg: the orchestrator's cheap local ffprobe check on the pulled .m4b.
# The heavy encoding never happens here - it all runs on beefy.
RUN apk add --no-cache openssh-client rsync ffmpeg \
 && pip install --no-cache-dir watchdog==6.0.0

RUN adduser -D -u 1000 -g 1000 merger
COPY app/watcher.py /app/watcher.py

USER merger
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "/app/watcher.py"]
