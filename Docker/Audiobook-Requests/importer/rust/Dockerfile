# Static musl binary, final image from scratch. Build: see README "Rust importer" (flock + CARGO_BUILD_JOBS=2 on fastpi).
FROM rust:1.91-alpine AS builder
RUN apk add --no-cache musl-dev gcc
WORKDIR /src
ENV CARGO_HOME=/usr/local/cargo CARGO_TERM_COLOR=never
ARG CARGO_BUILD_JOBS=2
ENV CARGO_BUILD_JOBS=$CARGO_BUILD_JOBS
# Dependencies first, so a source change does not recompile them.
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo 'fn main() {}' > src/main.rs
RUN --mount=type=cache,target=/usr/local/cargo/registry --mount=type=cache,target=/src/target \
    cargo build --release --locked && rm -rf src
COPY src ./src
RUN --mount=type=cache,target=/usr/local/cargo/registry --mount=type=cache,target=/src/target \
    touch src/main.rs && cargo build --release --locked && cp target/release/audiobook-importer /audiobook-importer

# Unit tests: docker build --target test .
FROM builder AS test
RUN --mount=type=cache,target=/usr/local/cargo/registry --mount=type=cache,target=/src/target \
    cargo test --profile test-release --locked

FROM scratch
COPY --from=builder /audiobook-importer /audiobook-importer
USER 65056:65056
EXPOSE 8000
ENTRYPOINT ["/audiobook-importer"]
