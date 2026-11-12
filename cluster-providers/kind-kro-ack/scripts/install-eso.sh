#!/usr/bin/env bash
# install-eso.sh -- install External Secrets Operator without a single point of failure
# on github.com.
#
# WHY: charts.external-secrets.io is a GitHub Pages index whose entry points at
# https://github.com/external-secrets/external-secrets/releases/download/helm-chart-<v>/...tgz.
# A github.com 504 / "context deadline exceeded" on that download used to abort
# `task install` (hub:install-eso, kro:install-eso-bootstrap) with no retry.
#
# HOW: the network part (fetching the chart) is split from the install, so a fetch failure
# is retried cheaply and a slow `--wait` is never re-run because of a download problem.
# Chart sources, tried in order, every attempt logs the source used:
#   1. repo      helm pull from https://charts.external-secrets.io  (ESO_RETRY_ATTEMPTS tries,
#                exponential back-off + jitter)
#   2. oci       helm pull from oci://ghcr.io/external-secrets/charts (ghcr.io, not the
#                github.com release CDN; ESO_OCI_ATTEMPTS tries)
# If both fail the script exits 1 with a clear error and installs nothing.
# Then `helm upgrade --install <chart.tgz> --wait --timeout $ESO_TIMEOUT`, once.
#
# Consumer-agnostic: no cluster, GitLab or workshop specifics. Cluster targeting comes only
# from the caller's environment (KUBECONFIG). Extra helm flags are passed after `--`.
#
# Usage: ESO_VERSION=2.4.1 [KUBECONFIG=...] install-eso.sh [-- <extra helm upgrade args>]
# Env:   ESO_VERSION (required), ESO_TIMEOUT (5m), ESO_RETRY_ATTEMPTS (5), ESO_OCI_ATTEMPTS (2),
#        ESO_RETRY_BASE (5, seconds; sleep = base*2^(n-1) + jitter in [0,base)), ESO_SLEEP (sleep),
#        ESO_REPO_URL, ESO_OCI_URL.
set -euo pipefail

ESO_VERSION="${ESO_VERSION:?set ESO_VERSION (core.yaml external-secrets.defaultVersion)}"
ESO_TIMEOUT="${ESO_TIMEOUT:-5m}"
ESO_RETRY_ATTEMPTS="${ESO_RETRY_ATTEMPTS:-5}"
ESO_OCI_ATTEMPTS="${ESO_OCI_ATTEMPTS:-2}"
ESO_RETRY_BASE="${ESO_RETRY_BASE:-5}"
ESO_SLEEP="${ESO_SLEEP:-sleep}"
ESO_REPO_URL="${ESO_REPO_URL:-https://charts.external-secrets.io}"
ESO_OCI_URL="${ESO_OCI_URL:-oci://ghcr.io/external-secrets/charts/external-secrets}"

[ "${1:-}" = "--" ] && shift

log() { printf '[install-eso] %s\n' "$*"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# pull_with_retry <label> <attempts> <helm pull args...>; leaves the tgz in $WORK.
pull_with_retry() {
  local label="$1" attempts="$2" n=1 delay
  shift 2
  while :; do
    rm -f "$WORK"/*.tgz
    log "source=$label attempt=$n/$attempts: helm pull (version $ESO_VERSION)"
    if helm pull "$@" --version "$ESO_VERSION" --destination "$WORK" \
      && [ -s "$WORK/external-secrets-$ESO_VERSION.tgz" ]; then
      log "source=$label attempt=$n/$attempts: chart fetched"
      return 0
    fi
    log "source=$label attempt=$n/$attempts: failed"
    [ "$n" -ge "$attempts" ] && return 1
    delay=$(( ESO_RETRY_BASE * (1 << (n - 1)) + RANDOM % (ESO_RETRY_BASE > 0 ? ESO_RETRY_BASE : 1) ))
    log "source=$label: retrying in ${delay}s"
    "$ESO_SLEEP" "$delay"
    n=$((n + 1))
  done
}

CHART=""
if pull_with_retry repo "$ESO_RETRY_ATTEMPTS" external-secrets --repo "$ESO_REPO_URL"; then
  CHART="$WORK/external-secrets-$ESO_VERSION.tgz"; SOURCE=repo
elif log "falling back to OCI"; pull_with_retry oci "$ESO_OCI_ATTEMPTS" "$ESO_OCI_URL"; then
  CHART="$WORK/external-secrets-$ESO_VERSION.tgz"; SOURCE=oci
else
  log "ERROR: could not fetch external-secrets chart $ESO_VERSION from the Helm repo ($ESO_REPO_URL, $ESO_RETRY_ATTEMPTS attempts) or OCI ($ESO_OCI_URL, $ESO_OCI_ATTEMPTS attempts); nothing was installed" >&2
  exit 1
fi

log "installing from source=$SOURCE chart=$CHART timeout=$ESO_TIMEOUT"
helm upgrade --install external-secrets "$CHART" \
  --namespace external-secrets --create-namespace \
  --set serviceAccount.name=external-secrets-sa \
  "$@" \
  --wait --timeout "$ESO_TIMEOUT"
log "installed (source=$SOURCE)"
