FROM python:3.13-alpine@sha256:7984cf56ceaddebe4fefeb75d64000b9f45d8b77b11a09b24524da6cdc3af0c8 AS thumbs
RUN echo "pillow==12.3.0 --hash=sha256:571b9fcb07b97ef3a492028fb3d2dc0993ca23a06138b0315286566d29ef718a" > /req.txt \
    && pip install --no-cache-dir --root-user-action=ignore --only-binary=:all: --require-hashes -r /req.txt
COPY scripts/build_thumbs.py /build_thumbs.py
COPY app/ /src/
RUN python /build_thumbs.py /src /thumbs

FROM python:3.13-alpine@sha256:7984cf56ceaddebe4fefeb75d64000b9f45d8b77b11a09b24524da6cdc3af0c8
RUN adduser -D -u 1000 picker
WORKDIR /app
COPY app/ /app/
COPY --from=thumbs /thumbs/ /app/thumbs/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000
EXPOSE 8080
CMD ["python", "-u", "/app/server.py"]
