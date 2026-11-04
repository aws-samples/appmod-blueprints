#!/usr/bin/env bash
# Wait for an EKS Argo CD capability to reach ACTIVE before the caller waits for its CRDs.
#
# Usage: wait-argocd-capability.sh <cluster-name> <region> [capability-name]
#   capability-name defaults to "argocd".
# Env:
#   ARGOCD_CAPABILITY_WAIT_SECS  ceiling in seconds (default 1800)
#   ARGOCD_CAPABILITY_POLL_SECS  poll interval in seconds (default 15)
#
# Exit codes:
#   0  ACTIVE (or DEGRADED: it was created; the caller's CRD wait decides)
#   1  ceiling reached while still not ACTIVE (CREATING, UPDATING, not created yet)
#   2  terminal status (CREATE_FAILED, DELETE_FAILED, DELETING)
#   64 usage error
#
# Why: hub:apply-root-appset used to wait only ~10 min for the ApplicationSet CRD. The
# capability is created asynchronously (by ACK from the kro EksCluster graph, or by the
# Crossplane composition) and can take well over 10 min to exist and turn ACTIVE, so the
# CRD wait timed out with no signal about the capability itself (int1105). This loop logs
# the capability status with elapsed seconds and fails fast on a terminal status.
set -uo pipefail

CLUSTER="${1:-}"
REGION="${2:-}"
NAME="${3:-argocd}"
if [ -z "$CLUSTER" ] || [ -z "$REGION" ]; then
  echo "usage: $0 <cluster-name> <region> [capability-name]" >&2
  exit 64
fi
CEILING="${ARGOCD_CAPABILITY_WAIT_SECS:-1800}"
POLL="${ARGOCD_CAPABILITY_POLL_SECS:-15}"

health() {
  aws eks describe-capability --cluster-name "$CLUSTER" --capability-name "$NAME" --region "$REGION" \
    --query 'capability.health.issues' --output json 2>/dev/null || echo "unavailable"
}

START=$(date +%s)
LAST=""
LAST_LOG=0
while :; do
  NOW=$(date +%s)
  ELAPSED=$((NOW - START))
  ERR=$(mktemp)
  STATUS=$(aws eks describe-capability --cluster-name "$CLUSTER" --capability-name "$NAME" --region "$REGION" \
    --query 'capability.status' --output text 2>"$ERR")
  RC=$?
  if [ "$RC" -ne 0 ] || [ -z "$STATUS" ] || [ "$STATUS" = "None" ]; then
    if grep -q 'ResourceNotFoundException' "$ERR" 2>/dev/null; then
      STATUS="NOT_CREATED"
    else
      STATUS="DESCRIBE_ERROR($(head -n1 "$ERR" 2>/dev/null | cut -c1-120))"
    fi
  fi
  rm -f "$ERR"

  case "$STATUS" in
    ACTIVE)
      printf '  [%ss] ✓ %s capability %s is ACTIVE\n' "$ELAPSED" "$CLUSTER" "$NAME"
      exit 0
      ;;
    DEGRADED)
      printf '  [%ss] ⚠ %s capability %s is DEGRADED (health: %s); continuing to the CRD wait\n' \
        "$ELAPSED" "$CLUSTER" "$NAME" "$(health)"
      exit 0
      ;;
    CREATE_FAILED|DELETE_FAILED|DELETING)
      printf '  [%ss] ✗ %s capability %s is %s (health: %s)\n' \
        "$ELAPSED" "$CLUSTER" "$NAME" "$STATUS" "$(health)" >&2
      exit 2
      ;;
  esac

  if [ "$ELAPSED" -ge "$CEILING" ]; then
    printf '  [%ss] ✗ %s capability %s not ACTIVE after %ss ceiling (status=%s, health: %s)\n' \
      "$ELAPSED" "$CLUSTER" "$NAME" "$CEILING" "$STATUS" "$(health)" >&2
    exit 1
  fi

  # Log on every status change, and at least once a minute while it stays the same.
  if [ "$STATUS" != "$LAST" ] || [ $((NOW - LAST_LOG)) -ge 60 ]; then
    printf '  [%ss] %s capability %s status=%s (waiting, ceiling %ss)\n' \
      "$ELAPSED" "$CLUSTER" "$NAME" "$STATUS" "$CEILING"
    LAST="$STATUS"
    LAST_LOG=$NOW
  fi
  sleep "$POLL"
done
