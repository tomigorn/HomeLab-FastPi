# Rust build (tests run here), then a scratch image with only the static binary.
# Legacy Python image: app/Dockerfile.python (kept for rollback until the owner removes it).
FROM rust:1-alpine@sha256:44819b27be4c97b0e4d7203bd2e02c4820f97700211b6a37fb4c246a2de59383 AS build
RUN apk add --no-cache musl-dev
ENV CARGO_BUILD_JOBS=2 CARGO_TERM_COLOR=never
WORKDIR /src
COPY rust/Cargo.toml rust/Cargo.lock ./
COPY rust/src ./src
RUN --mount=type=cache,target=/usr/local/cargo/registry,id=beefy-waker-registry \
    --mount=type=cache,target=/src/target,id=beefy-waker-target \
    cargo test --release --locked && cargo build --release --locked \
 && cp target/release/beefy-waker /beefy-waker \
 && mkdir -p /cache && chown 65005:65005 /cache && chmod 700 /cache

FROM scratch
COPY --from=build /beefy-waker /beefy-waker
# /tmp holds the Jellyfin public-info cache; compose mounts a named volume here, which takes this owner
COPY --from=build --chown=65005:65005 /cache /tmp
USER 65005:65005
ENTRYPOINT ["/beefy-waker"]
