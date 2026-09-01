#!/usr/bin/env bash
# Reusable `domainResolver` for CloudFront exposure: prints the platform distribution's
# domain name once it exists. Used by the in-repo workshop and by external consumers
# (e.g. OAP) — wire it up with, in config.local.yaml:
#
#     domain: ""
#     domainResolver: "scripts/resolve-cloudfront-domain.sh"
#
# Contract (see config.yaml): block until the hostname is known, print it as the last
# non-empty line of stdout, exit 0. Progress goes to stderr.
#
# It waits for the distribution to EXIST, not to be Deployed: create-distribution returns
# DomainName immediately, and the platform only needs the hostname to template ingress
# rules. Deployment status matters for serving traffic, which happens later regardless.
#
# Inputs (all optional; PLATFORM_* are exported by the platform's domain:resolve):
#   PLATFORM_CONFIG_FILE  path to config.local.yaml (used to derive the Comment)
#   PLATFORM_REPO_ROOT    platform repo root (fallback for locating the config)
#   CF_DISTRIBUTION_ID    look up this distribution directly
#   CF_COMMENT            match on this Comment (default: "<hub.clusterName>-platform")
#   CF_TIMEOUT_SECONDS    default 900        CF_POLL_SECONDS  default 15
#
# Looks the distribution up on every run rather than reading a recorded value, so it is
# idempotent and survives the distribution or ALB being recreated.
set -euo pipefail

log(){ printf '[resolve-cf] %s\n' "$*" >&2; }
# $1 = message, $2 = exit code. Must not use $* here — that would print the code too.
die(){ printf '[resolve-cf] ERROR: %s\n' "$1" >&2; exit "${2:-1}"; }

command -v aws >/dev/null 2>&1 || die "aws CLI not found on PATH"
TIMEOUT="${CF_TIMEOUT_SECONDS:-900}"; POLL="${CF_POLL_SECONDS:-15}"

COMMENT="${CF_COMMENT:-}"
if [ -z "${CF_DISTRIBUTION_ID:-}" ] && [ -z "$COMMENT" ]; then
  CFG="${PLATFORM_CONFIG_FILE:-${PLATFORM_REPO_ROOT:-.}/config.local.yaml}"
  [ -f "$CFG" ] || die "cannot locate config.local.yaml (set PLATFORM_CONFIG_FILE, CF_COMMENT or CF_DISTRIBUTION_ID)"
  command -v yq >/dev/null 2>&1 || die "yq not found on PATH (needed to read $CFG)"
  CLUSTER=$(yq '.hub.clusterName // ""' "$CFG" 2>/dev/null | tr -d '[:space:]' || true)
  [ "$CLUSTER" = "null" ] && CLUSTER=""
  [ -n "$CLUSTER" ] || die "hub.clusterName not set in $CFG — cannot derive the distribution Comment"
  # Must match the Comment that create-config.sh sets on the distribution.
  COMMENT="${CLUSTER}-platform"
fi

lookup(){
  if [ -n "${CF_DISTRIBUTION_ID:-}" ]; then
    aws cloudfront get-distribution --id "$CF_DISTRIBUTION_ID" \
      --query 'Distribution.DomainName' --output text 2>/dev/null || true
  else
    aws cloudfront list-distributions \
      --query "DistributionList.Items[?Comment=='${COMMENT}'].DomainName | [0]" \
      --output text 2>/dev/null || true
  fi
}

log "waiting for CloudFront distribution ${CF_DISTRIBUTION_ID:+id=$CF_DISTRIBUTION_ID}${COMMENT:+Comment='$COMMENT'}"
ELAPSED=0
while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
  D=$(lookup | tr -d '[:space:]')
  if [ -n "$D" ] && [ "$D" != "None" ]; then
    log "found after ${ELAPSED}s"
    printf '%s\n' "$D"
    exit 0
  fi
  sleep "$POLL"; ELAPSED=$((ELAPSED + POLL))
done

die "no distribution found within ${TIMEOUT}s. The provisioning job that creates the ALB and
       distribution has probably failed — for the in-repo workshop see the log under
       \$REPO_ROOT/private/platform-infra/." 2
