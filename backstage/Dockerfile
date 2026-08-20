# Backstage image based on CNOE backstage-app with workshop-specific patches:
# - /backstage sub-path support (baseUrl)
# - GitLab scaffolder module
# - kube:apply action alias with manifest input + in-cluster fallback
#
# To rebuild: docker build -t <ecr-repo>/backstage:latest backstage/

# Stage 1: Clone CNOE source and apply patches
FROM node:22-bookworm-slim AS source

RUN apt-get update && apt-get install -y --no-install-recommends git patch ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --depth 1 https://github.com/cnoe-io/backstage-app.git .

COPY patches/cnoe-customizations.patch /tmp/
RUN patch -p1 < /tmp/cnoe-customizations.patch

# Stage 2: Install and build (mirrors CNOE Dockerfile)
FROM node:22-bookworm-slim AS build

USER node
WORKDIR /app

COPY --from=source --chown=node:node /build/package.json /build/yarn.lock ./
COPY --from=source --chown=node:node /build/packages packages
COPY --from=source --chown=node:node /build/plugins plugins

RUN --mount=type=cache,target=/home/node/.cache/yarn,sharing=locked,uid=1000,gid=1000 \
    yarn install --frozen-lockfile --network-timeout 600000

COPY --from=source --chown=node:node /build .

RUN yarn tsc
RUN yarn --cwd packages/backend build

RUN mkdir packages/backend/dist/skeleton packages/backend/dist/bundle \
    && tar xzf packages/backend/dist/skeleton.tar.gz -C packages/backend/dist/skeleton \
    && tar xzf packages/backend/dist/bundle.tar.gz -C packages/backend/dist/bundle

# Stage 3: Production image
FROM node:22-bookworm-slim

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip python3-venv g++ build-essential ca-certificates curl

RUN yarn config set python /usr/bin/python3

# kubectl for kube:apply action
RUN curl -L -o /usr/local/bin/kubectl https://dl.k8s.io/release/v1.29.9/bin/linux/amd64/kubectl && chmod +x /usr/local/bin/kubectl

# mkdocs for TechDocs
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN pip3 install 'mkdocs-techdocs-core==1.4.2'

USER node
WORKDIR /app

COPY --from=build --chown=node:node /app/yarn.lock /app/package.json /app/packages/backend/dist/skeleton/ ./

RUN --mount=type=cache,target=/home/node/.cache/yarn,sharing=locked,uid=1000,gid=1000 \
    yarn install --frozen-lockfile --production --network-timeout 600000

COPY --from=build --chown=node:node /app/packages/backend/dist/bundle/ ./
COPY --from=source --chown=node:node /build/app-config.yaml /build/app-config.production.yaml ./

ENV NODE_ENV production
ENV NODE_OPTIONS="--no-node-snapshot"
CMD ["node", "packages/backend", "--config", "app-config.yaml", "--config", "app-config.production.yaml"]
