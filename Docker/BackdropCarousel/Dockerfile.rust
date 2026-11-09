FROM rust:1.91-alpine@sha256:45c1c35cd364b8055e9e86f8ecd3e8c874b2dcb658d8a4f94b5d111aa0d651a2 AS build
ENV CARGO_BUILD_JOBS=2
WORKDIR /src
COPY rust/Cargo.toml rust/Cargo.lock* ./
COPY rust/src ./src
RUN --mount=type=cache,target=/usr/local/cargo/registry --mount=type=cache,target=/src/target,id=backdrop-carousel-target \
    cargo test --release --locked && cargo build --release --locked && cp target/release/backdrop-carousel /backdrop-carousel

FROM scratch
COPY --from=build /backdrop-carousel /backdrop-carousel
USER 65008:65008
EXPOSE 8000
ENTRYPOINT ["/backdrop-carousel"]
