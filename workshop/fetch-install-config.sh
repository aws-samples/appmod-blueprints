#!/usr/bin/env bash
#
# fetch-install-config.sh: give the IDE the config.local.yaml that the remote install
# (task install:remote, in CodeBuild) generated, instead of generating its own.
#
# Why: in the remote install the CodeBuild project runs create-config.sh (it reserves the
# CloudFront hostname, finds IdC) and publishes the result, read-only for everybody else, in
# Secrets Manager (<prefix>/install-config). The IDE copies it. The opposite direction is
# never used: the build must not read anything the IDE (the participant's terminal) wrote.
#
#   RESOURCE_PREFIX            required
#   OUTPUT_FILE                default <repo>/config.local.yaml
#   INSTALL_CONFIG_WAIT        seconds to wait for the secret (default 1800)
#
# Standalone script, not a task: every task reads config.local.yaml at parse time.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_FILE="${OUTPUT_FILE:-$REPO_ROOT/config.local.yaml}"
PREFIX="${RESOURCE_PREFIX:?RESOURCE_PREFIX is required}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
MAX="${INSTALL_CONFIG_WAIT:-1800}"
W=0
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
echo "▸ Waiting for ${PREFIX}/install-config (published by the CodeBuild install), max ${MAX}s..."
# A config published before the newest ${PREFIX}-install build started is an earlier build's:
# keep waiting for the new build to publish its own. If the build list cannot be read, say so
# and use the config (the wait's own cut-off still applies afterwards).
newest_build_start() {
  B=$(aws codebuild list-builds-for-project --project-name "${PREFIX}-install" --sort-order DESCENDING \
        ${REGION:+--region "$REGION"} --query 'ids[0]' --output text 2>/dev/null) || return 1
  case "$B" in ""|None) echo ""; return 0 ;; esac
  T=$(aws codebuild batch-get-builds --ids "$B" ${REGION:+--region "$REGION"} --query 'builds[0].startTime' --output text 2>/dev/null) || return 1
  to_epoch "$T"
}
to_epoch() {
  case "$1" in ""|None) echo "" ;; *[!0-9.]*) date -d "$1" +%s 2>/dev/null || echo "" ;; *) echo "${1%%.*}" ;; esac
}
SAID=""
while [ "$W" -lt "$MAX" ]; do
  if aws secretsmanager get-secret-value --secret-id "${PREFIX}/install-config" ${REGION:+--region "$REGION"} \
       --query SecretString --output text > "$TMP" 2>/dev/null && yq '.' "$TMP" >/dev/null 2>&1 \
       && [ -n "$(yq '.hub.clusterName // ""' "$TMP")" ]; then
    if START=$(newest_build_start); then
      PUB=$(to_epoch "$(aws secretsmanager describe-secret --secret-id "${PREFIX}/install-config" ${REGION:+--region "$REGION"} \
              --query LastChangedDate --output text 2>/dev/null || true)")
      if [ -n "$START" ] && [ -z "$PUB" ]; then
        echo "  ⚠ could not read when ${PREFIX}/install-config was published: using it as published" >&2
        break
      elif [ -n "$START" ] && [ "$PUB" -lt "$START" ]; then
        [ -n "$SAID" ] || echo "  ${PREFIX}/install-config is from an earlier build (published before the newest build started): waiting for the new one"
        SAID=1
      else
        break
      fi
    else
      echo "  ⚠ could not list the ${PREFIX}-install builds: using ${PREFIX}/install-config as published" >&2
      break
    fi
  fi
  sleep "${INSTALL_CONFIG_POLL:-10}"
  W=$((W + ${INSTALL_CONFIG_POLL:-10}))
done
if [ "$W" -ge "$MAX" ]; then
  echo "✗ ${PREFIX}/install-config not available after ${MAX}s: the CodeBuild install did not reach create-config.sh (aws logs tail /aws/codebuild/${PREFIX}-install)" >&2
  exit 1
fi
# The IDE runs as itself: the build-only keys (named install profile, remote GitLab wait) do
# not apply here. The build publishes the file before adding them; strip them anyway.
# privilegedSteps: external is what makes `task destroy` on this host Kubernetes-only (the
# AWS deletes are the stack sweep's job, this role has none): see workshop destroy.
yq -i 'del(.gitlabInit) | del(.aws.ideRoleArn) | del(.aws.installRoleArn) | .privilegedSteps = "external"' "$TMP"
if [ "$(yq '.aws.profile // ""' "$TMP")" = "install" ]; then yq -i '.aws.profile = "default"' "$TMP"; fi
install -m 600 "$TMP" "$OUTPUT_FILE"
echo "✓ wrote $OUTPUT_FILE from ${PREFIX}/install-config"
