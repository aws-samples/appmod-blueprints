# Dockerfile for creating a statically-linked Rust application using docker's
# multi-stage build feature. This also leverages the docker build cache to avoid
# re-downloading dependencies if they have not changed.
FROM rust AS build
WORKDIR /usr/app

ENV RUSTFLAGS='-C linker=x86_64-linux-gnu-gcc'
ENV CC_x86_64_unknown_linux_musl=clang
ENV AR_x86_64_unknown_linux_musl=llvm-ar
ENV CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_RUSTFLAGS="-Clink-self-contained=yes -Clinker=rust-lld"
ENV CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_RUNNER="qemu-x86_64 -L /usr/x86-64-linux-gnu"

RUN rustup target add x86_64-unknown-linux-musl
RUN apt update && apt install -y musl-tools musl-dev build-essential gcc-x86-64-linux-gnu clang llvm

# Download the target for static linking.
RUN rustup target add x86_64-unknown-linux-musl

COPY Cargo.toml Cargo.lock ./
COPY src/api/ ./src/api/

# Required for Rocket
RUN update-ca-certificates

RUN cargo build --bin api --target x86_64-unknown-linux-musl --release

# Copy the statically-linked binary into a scratch container.
FROM scratch

COPY --from=build /usr/app/target/x86_64-unknown-linux-musl/release/api .

# steal the CA certs from our builder in production
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

USER 1000

ENV ROCKET_ADDRESS=0.0.0.0
ENV ROCKET_PORT=8080

CMD ["./api"]