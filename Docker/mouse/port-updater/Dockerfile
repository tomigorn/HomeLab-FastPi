# Static musl binary on scratch. `docker build --target test .` runs the unit tests.
FROM rust:1.91-alpine AS build
RUN apk add --no-cache musl-dev
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY src src
RUN --mount=type=cache,target=/usr/local/cargo/registry --mount=type=cache,target=/src/target,id=port-updater-target \
    CARGO_BUILD_JOBS=2 cargo build --release --locked && cp target/release/port-updater /port-updater

FROM build AS test
RUN --mount=type=cache,target=/usr/local/cargo/registry --mount=type=cache,target=/src/target,id=port-updater-target \
    CARGO_BUILD_JOBS=2 cargo test --release --locked

FROM scratch
COPY --from=build /port-updater /port-updater
USER 65042:65042
ENTRYPOINT ["/port-updater"]
