# Dockerfile for creating a statically-linked Rust application using docker's
# multi-stage build feature. This also leverages the docker build cache to avoid
# re-downloading dependencies if they have not changed. 
FROM rust:1.79-slim AS build
WORKDIR /usr/app

ENV RUSTFLAGS='-C linker=x86_64-linux-gnu-gcc'
ENV CC_x86_64_unknown_linux_musl=clang
ENV AR_x86_64_unknown_linux_musl=llvm-ar
ENV CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_RUSTFLAGS="-Clink-self-contained=yes -Clinker=rust-lld"

RUN apt-get update && apt-get install -y --no-install-recommends \
    musl-tools musl-dev build-essential gcc-x86-64-linux-gnu clang llvm ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    rustup target add x86_64-unknown-linux-musl

# Copy manifests and build dependencies first
COPY Cargo.toml Cargo.lock ./
RUN mkdir -p src/api && echo "fn main() {}" > src/api/main.rs && \
    cargo build --release --bin api --target x86_64-unknown-linux-musl

# Copy actual source and build
COPY src/api/ ./src/api/
RUN cargo build --release --bin api --target x86_64-unknown-linux-musl && \
    cp target/x86_64-unknown-linux-musl/release/api ./api


# Copy the statically-linked binary into a scratch container.
FROM scratch

COPY --from=build /usr/app/api .
COPY --from=build /usr/app/src/api/res/products.csv .
COPY --from=build /usr/app/src/api/res/variants.csv .

# steal the CA certs from our builder in production
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

USER 1000

ENV ROCKET_ADDRESS=0.0.0.0
ENV ROCKET_PORT=8080

CMD ["./api"]