#!/bin/sh
# Delete exact IAM roles (attached policies detached, inline policies deleted first).
# Used by `task privileged:destroy`, the privilegedSteps runner's teardown of the roles
# privileged:pre created. Never a pattern: only the role names given as arguments.
#
#   HUB_CLUSTER=<hub> AWS_REGION=<region> [SCOPED_POLICY_ACCOUNT=<account-id> RESOURCE_PREFIX=<prefix>] \
#     sh iam-role-delete.sh ROLE...
#
# With SCOPED_POLICY_ACCOUNT set, each role's scoped customer-managed policy
# (common/iam/managed-policy.sh delete) is deleted too.
#
# Refuses while the hub EKS cluster still exists (its ACK capability and Crossplane
# providers still use these roles), and when that cannot be read. A role that is already
# gone is fine; any other error is printed and the script exits 1 after trying them all.
set -eu
: "${HUB_CLUSTER:?HUB_CLUSTER is required}"
: "${AWS_REGION:?AWS_REGION is required}"
HERE=$(cd "$(dirname "$0")" && pwd)
IAM_ROLE_CHECK_LIB=1 . "$HERE/iam-role-check.sh"

if HUB_ERR=$(aws eks describe-cluster --name "$HUB_CLUSTER" --region "$AWS_REGION" \
    --query 'cluster.status' --output text 2>&1); then
  echo "✗ the hub cluster $HUB_CLUSTER still exists ($HUB_ERR): delete it first, with task destroy." >&2
  echo "  On kind-kro-ack, task destroy under privilegedSteps: external does not delete the hub: run the stack sweep, or task destroy again with privilegedSteps: inline and credentials allowed to make its AWS deletes." >&2
  exit 1
fi
case "$HUB_ERR" in
  *ResourceNotFoundException*) ;;
  *) echo "✗ cannot read the hub cluster $HUB_CLUSTER: $(printf '%s' "$HUB_ERR" | tr '\n' ' ')" >&2; exit 1 ;;
esac

FAILED=""
fail() { FAILED="${FAILED}    - $1: $(printf '%s' "$2" | tr '\n' ' ')
"; }
# The scoped customer-managed policy install created for a role (managed-policy.sh):
# detached and deleted, not left behind. A no-op for a role that has none; also run when
# the role is already gone (managed-policy.sh delete treats a missing role as success).
delete_scoped() {
  [ -n "${SCOPED_POLICY_ACCOUNT:-}" ] || return 0
  if ! E=$(sh "$HERE/../iam/managed-policy.sh" delete "$SCOPED_POLICY_ACCOUNT" "${RESOURCE_PREFIX:?RESOURCE_PREFIX is required with SCOPED_POLICY_ACCOUNT}" "$1" 2>&1 >/dev/null); then
    fail "$1 (scoped policy)" "$E"; return 1
  fi
}
for ROLE in "$@"; do
  STATE=$(iam_role_state "$ROLE")
  case "$STATE" in
    missing) echo "  $ROLE already gone"; delete_scoped "$ROLE" || true; continue ;;
    present) ;;
    *) fail "$ROLE" "${STATE#error: }"; continue ;;
  esac
  delete_scoped "$ROLE" || continue
  if ! OUT=$(aws iam list-attached-role-policies --role-name "$ROLE" \
      --query 'AttachedPolicies[].PolicyArn' --output text 2>&1); then
    fail "$ROLE" "$OUT"; continue
  fi
  ERR=""
  for ARN in $OUT; do
    [ "$ARN" = None ] && continue
    E=$(aws iam detach-role-policy --role-name "$ROLE" --policy-arn "$ARN" 2>&1) || ERR="$E"
  done
  if ! OUT=$(aws iam list-role-policies --role-name "$ROLE" --query 'PolicyNames[]' --output text 2>&1); then
    fail "$ROLE" "$OUT"; continue
  fi
  for P in $OUT; do
    [ "$P" = None ] && continue
    E=$(aws iam delete-role-policy --role-name "$ROLE" --policy-name "$P" 2>&1) || ERR="$E"
  done
  if E=$(aws iam delete-role --role-name "$ROLE" 2>&1); then
    echo "  ✓ deleted IAM role $ROLE"
  else
    fail "$ROLE" "${ERR:-$E}"
  fi
done
if [ -n "$FAILED" ]; then
  echo "✗ these IAM roles were not deleted:" >&2
  printf '%s' "$FAILED" >&2
  exit 1
fi
