#!/bin/bash
# ensure-gitlab-compose.sh: precondition for the workshop `gitlab:init-ec2` task (workshop layer,
# NOT a cluster provider). Idempotent; a no-op when the docker compose plugin works and GitLab runs.
#   1. `docker compose version` must work, else install the pinned plugin (sha256-verified, retried)
#      into the user plugin dir (no sudo).
#   2. `docker compose up -d` for $GITLAB_HOME when the GitLab container is not running (rc propagates).
#   3. Wait (bounded) for the container to report healthy.
#
# Plugin source, from PEEKS_TOOLS_SOURCE:
#   (unset)|github  GitHub release only
#   s3-first        S3 mirror first (needs ASSETS_BUCKET_NAME), then GitHub
#   s3-only         S3 mirror only; never contacts GitHub
# S3 object: s3://$ASSETS_BUCKET_NAME/${ASSETS_BUCKET_PREFIX}tools/v1/docker-compose-<ver>-linux-x86_64
#
# Exit: 0 ok | 10 plugin not installable | 11 compose file missing | 12 up -d failed | 13 not healthy in time
# Every failure prints one line starting with PEEKS_PRECONDITION_FAILED.
# shortcut: x86_64 only (IDE is x86_64), upgrade when an arm64 IDE is supported.
set -u
COMPOSE_VERSION=${COMPOSE_VERSION:-v2.27.1}
COMPOSE_SHA256=${COMPOSE_SHA256:-ddc876fe2a89d5b7ea455146b0975bfe52904eecba9b192193377d6f99d69ad9}
COMPOSE_URL=${COMPOSE_URL:-https://github.com/docker/compose/releases/download/$COMPOSE_VERSION/docker-compose-linux-x86_64}
GITLAB_HOME=${GITLAB_HOME:-$HOME/gitlab}
PLUGIN_DIR=${PLUGIN_DIR:-$HOME/.docker/cli-plugins}
ATTEMPTS=${ATTEMPTS:-5}
BACKOFF_BASE=${BACKOFF_BASE:-2}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-1200}
HEALTH_INTERVAL=${HEALTH_INTERVAL:-10}
SOURCE=${PEEKS_TOOLS_SOURCE:-github}

log() { echo "[ensure-gitlab-compose] $(date +%H:%M:%S) $*" >&2; }
fail() { echo "PEEKS_PRECONDITION_FAILED: $2" >&2; exit "$1"; }
compose_ok() { docker compose version >/dev/null 2>&1; }

# verify FILE: sha256 must match the pinned value
verify() { [ "$(sha256sum "$1" 2>/dev/null | cut -d' ' -f1)" = "$COMPOSE_SHA256" ]; }

fetch_github() { # $1 = tmp file
  local n=1
  while [ "$n" -le "$ATTEMPTS" ]; do
    log "GitHub download attempt $n/$ATTEMPTS"
    rm -f "$1"
    curl -fsSL --connect-timeout 15 --max-time 300 -o "$1" "$COMPOSE_URL" && verify "$1" && return 0
    [ "$n" -lt "$ATTEMPTS" ] && sleep $(( BACKOFF_BASE * (1 << n) ))
    n=$((n + 1))
  done
  return 1
}

fetch_s3() { # $1 = tmp file
  local prefix=${ASSETS_BUCKET_PREFIX:-} n=1
  if [ -z "${ASSETS_BUCKET_NAME:-}" ]; then log "ASSETS_BUCKET_NAME not set, S3 mirror unavailable"; return 1; fi
  [ -n "$prefix" ] && [ "${prefix%/}" = "$prefix" ] && prefix="$prefix/"
  local uri="s3://$ASSETS_BUCKET_NAME/${prefix}tools/v1/docker-compose-$COMPOSE_VERSION-linux-x86_64"
  while [ "$n" -le 3 ]; do
    log "S3 download attempt $n/3 $uri"
    rm -f "$1"
    aws s3 cp "$uri" "$1" --only-show-errors && verify "$1" && return 0
    [ "$n" -lt 3 ] && sleep $(( BACKOFF_BASE * (1 << n) ))
    n=$((n + 1))
  done
  return 1
}

install_plugin() {
  local dest="$PLUGIN_DIR/docker-compose" tmp ok=1
  mkdir -p "$PLUGIN_DIR"; tmp="$dest.part.$$"
  case "$SOURCE" in
    s3-only)  fetch_s3 "$tmp"; ok=$? ;;
    s3-first) fetch_s3 "$tmp" || fetch_github "$tmp"; ok=$? ;;
    github)   fetch_github "$tmp"; ok=$? ;;
    *) rm -f "$tmp"; fail 10 "unknown PEEKS_TOOLS_SOURCE='$SOURCE' (expected github|s3-first|s3-only)" ;;
  esac
  if [ "$ok" -eq 0 ]; then chmod 755 "$tmp" && mv -f "$tmp" "$dest"; return; fi
  rm -f "$tmp"; return 1
}

if compose_ok; then
  log "docker compose present: $(docker compose version 2>/dev/null)"
else
  log "docker compose missing or not runnable, installing $COMPOSE_VERSION into $PLUGIN_DIR (source: $SOURCE)"
  install_plugin || fail 10 "docker compose plugin $COMPOSE_VERSION could not be installed (source: $SOURCE); GitLab cannot start"
  compose_ok || fail 10 "docker compose plugin installed but 'docker compose version' still fails"
  log "docker compose installed: $(docker compose version 2>/dev/null)"
fi

CF="$GITLAB_HOME/docker-compose.yml"
[ -f "$CF" ] || fail 11 "$CF missing (bootstrap did not reach the GitLab section)"

if [ -z "$(docker compose -f "$CF" ps -q --status running 2>/dev/null)" ]; then
  log "GitLab container not running, starting it (image pull + first boot take several minutes)"
  up=1
  for n in 1 2 3; do
    docker compose -f "$CF" up -d && { up=0; break; }
    log "docker compose up -d attempt $n/3 failed"
    [ "$n" -lt 3 ] && sleep $(( BACKOFF_BASE * (1 << n) * 5 ))
  done
  [ "$up" -eq 0 ] || fail 12 "docker compose up -d failed 3 times (Docker Hub pull?); see 'docker compose -f $CF logs'"
else
  log "GitLab container already running"
fi

# Bounded wait for healthy. An image without a healthcheck reports "none": running is then enough.
waited=0
while :; do
  cid=$(docker compose -f "$CF" ps -q 2>/dev/null | head -n1)
  st=$([ -n "$cid" ] && docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null)
  case "$st" in healthy|none) log "GitLab container status: $st"; exit 0 ;; esac
  [ "$waited" -ge "$HEALTH_TIMEOUT" ] && fail 13 "GitLab container not healthy after ${HEALTH_TIMEOUT}s (status: ${st:-absent})"
  sleep "$HEALTH_INTERVAL"; waited=$((waited + HEALTH_INTERVAL))
done
