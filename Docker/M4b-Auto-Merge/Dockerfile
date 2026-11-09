# Build context: the project folder (Docker/M4b-Auto-Merge).
FROM rust:1-alpine AS build
RUN apk add --no-cache musl-dev
WORKDIR /src
COPY rust/Cargo.toml rust/Cargo.lock* ./
COPY rust/src ./src
ENV CARGO_BUILD_JOBS=2
RUN cargo test --release --locked && cargo build --release --locked && cp target/release/m4b-auto-merge /m4b-auto-merge

FROM rust:1-alpine AS lock
WORKDIR /src
COPY rust/Cargo.toml ./
COPY rust/src ./src
RUN cargo generate-lockfile

FROM scratch AS lockfile
COPY --from=lock /src/Cargo.lock /Cargo.lock

# The orchestrator this triggers (m4b-merge/orchestrate.py, mounted read-only) is Python and needs ssh, rsync and ffprobe, so the final stage keeps that runtime.
FROM python:3.12-alpine
RUN apk add --no-cache openssh-client rsync ffmpeg \
 && adduser -D -u 65018 merger
COPY --from=build /m4b-auto-merge /usr/local/bin/m4b-auto-merge
USER merger
ENTRYPOINT ["/usr/local/bin/m4b-auto-merge"]
