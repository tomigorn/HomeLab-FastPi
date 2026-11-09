FROM rust:1.91-alpine@sha256:45c1c35cd364b8055e9e86f8ecd3e8c874b2dcb658d8a4f94b5d111aa0d651a2 AS build
ENV CARGO_BUILD_JOBS=2
WORKDIR /src
COPY Cargo.toml Cargo.lock* ./
COPY src ./src
RUN if [ -f Cargo.lock ]; then cargo build --release --locked; else cargo build --release; fi \
 && cargo test --release

FROM scratch
COPY --from=build /src/target/release/answer-inbox /answer-inbox
USER 65003:65003
ENTRYPOINT ["/answer-inbox"]
