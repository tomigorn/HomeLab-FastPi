# Rust build (tests run here), then a scratch image with only the static binary.
# Legacy Python image: app/Dockerfile.python (kept for rollback until the owner removes it).
FROM rust:1-alpine@sha256:2cccd8b212b37dad15a555589c1b6787da4ab913fe24d8a9b2d99d3498869409 AS build
RUN apk add --no-cache musl-dev
ENV CARGO_BUILD_JOBS=2 CARGO_TERM_COLOR=never
WORKDIR /src
COPY rust/Cargo.toml rust/Cargo.lock ./
COPY rust/src ./src
RUN --mount=type=cache,target=/usr/local/cargo/registry,id=tower-waker-registry \
    --mount=type=cache,target=/src/target,id=tower-waker-target \
    cargo test --release --locked && cargo build --release --locked \
 && cp target/release/tower-waker /tower-waker

FROM scratch
COPY --from=build /tower-waker /tower-waker
USER 65006:65006
ENTRYPOINT ["/tower-waker"]
