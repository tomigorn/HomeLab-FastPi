FROM python:3.13-alpine@sha256:7984cf56ceaddebe4fefeb75d64000b9f45d8b77b11a09b24524da6cdc3af0c8 AS thumbs
RUN echo "pillow==12.3.0 --hash=sha256:571b9fcb07b97ef3a492028fb3d2dc0993ca23a06138b0315286566d29ef718a" > /req.txt \
    && pip install --no-cache-dir --root-user-action=ignore --only-binary=:all: --require-hashes -r /req.txt
COPY scripts/build_thumbs.py /build_thumbs.py
COPY app/ /src/
RUN python /build_thumbs.py /src /thumbs

FROM rust:1.91-alpine@sha256:45c1c35cd364b8055e9e86f8ecd3e8c874b2dcb658d8a4f94b5d111aa0d651a2 AS build
ENV CARGO_BUILD_JOBS=2
WORKDIR /src
COPY rust/Cargo.toml rust/Cargo.lock* ./
COPY rust/src ./src
RUN --mount=type=cache,target=/usr/local/cargo/registry --mount=type=cache,target=/src/target,id=avatar-picker-target \
    if [ -f Cargo.lock ]; then L=--locked; fi; cargo test --release $L && cargo build --release $L \
    && cp target/release/avatar-picker /avatar-picker && cp Cargo.lock /Cargo.lock

FROM scratch AS lock
COPY --from=build /Cargo.lock /Cargo.lock

FROM scratch AS bin
COPY --from=build /avatar-picker /avatar-picker

FROM scratch
COPY --from=build /avatar-picker /avatar-picker
COPY app/gallery.json app/groups.json app/VERSION /app/
COPY app/static/ /app/static/
COPY app/img/ /app/img/
COPY app/img-local/ /app/img-local/
COPY --from=thumbs /thumbs/ /app/thumbs/
USER 65002:65002
EXPOSE 8080
ENTRYPOINT ["/avatar-picker"]
