# Rust build (cargo test runs here), then a scratch image with only the static binary.
# Targets: lock (export Cargo.lock), bin (export the binary for the black-box suite), default = the image.
FROM rust:1-alpine@sha256:2cccd8b212b37dad15a555589c1b6787da4ab913fe24d8a9b2d99d3498869409 AS build
RUN apk add --no-cache musl-dev
ARG CARGO_BUILD_JOBS=2
ENV CARGO_BUILD_JOBS=${CARGO_BUILD_JOBS} CARGO_TERM_COLOR=never
WORKDIR /src
COPY rust/Cargo.toml rust/Cargo.lock* ./
COPY rust/src ./src
COPY rust/fixtures ./fixtures
COPY www /www
RUN --mount=type=cache,target=/usr/local/cargo/registry,id=activity-registry \
    --mount=type=cache,target=/src/target,id=activity-target \
    if [ -f Cargo.lock ]; then L=--locked; fi; cargo test --release $L && cargo build --release $L \
 && cp target/release/activity /activity && cp Cargo.lock /Cargo.lock \
 && mkdir -p /data-dir && chown 65060:65060 /data-dir

FROM scratch AS lock
COPY --from=build /Cargo.lock /Cargo.lock

FROM scratch AS bin
COPY --from=build /activity /activity

FROM scratch
COPY --from=build /activity /activity
COPY --from=build --chown=65060:65060 /data-dir /data
USER 65060:65060
EXPOSE 8080
ENTRYPOINT ["/activity"]
