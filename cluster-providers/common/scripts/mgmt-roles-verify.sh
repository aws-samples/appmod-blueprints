#!/bin/sh
# Read-only check of the <prefix>-cluster-mgmt-* IAM roles that `hub:create-mgmt-roles`
# creates, plus any role named as an argument (existence only). Used when config.yaml
# sets `privilegedSteps: external`: a separate, more privileged runner (e.g. a CodeBuild
# project running `task privileged:pre`) created the roles, and the install host only needs iam:GetRole / ListAttachedRolePolicies /
# GetRolePolicy (all in the AWS ReadOnlyAccess managed policy) to confirm they are there.
#
# Fails (exit 1) listing every missing role/policy, so an install that depends on the
# external runner stops at once instead of leaving ACK stuck on "data pending" later.
# Keep SERVICES / expected_policies in sync with get_policies() in
# cluster-providers/kind-{kro-ack,crossplane}/Taskfile.yaml (hub:create-mgmt-roles:apply);
# workshop/scripts/tests/test_privileged_offload.py enforces it.
set -eu

: "${RESOURCE_PREFIX:?RESOURCE_PREFIX is required}"
SERVICES="ec2 eks iam ecr s3 dynamodb secretsmanager rds"

expected_policies() {
  case $1 in
    ec2) echo "arn:aws:iam::aws:policy/AmazonEC2FullAccess arn:aws:iam::aws:policy/AmazonVPCFullAccess";;
    eks) echo "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy arn:aws:iam::aws:policy/AmazonEKSServicePolicy arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly";;
    # iam: no AWS managed policy; the customer-managed <prefix>-cluster-mgmt-iam-scoped
    # (checked by name below) replaces IAMFullAccess.
    iam) echo "";;
    ecr) echo "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryFullAccess";;
    s3) echo "arn:aws:iam::aws:policy/AmazonS3FullAccess";;
    dynamodb) echo "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess";;
    secretsmanager) echo "arn:aws:iam::aws:policy/SecretsManagerReadWrite";;
    rds) echo "arn:aws:iam::aws:policy/AmazonRDSFullAccess arn:aws:iam::aws:policy/SecretsManagerReadWrite";;
  esac
}

# Only NoSuchEntity means missing; any other read error (expired credentials,
# AccessDenied...) is printed as such, never blamed on privileged:pre.
HERE=$(cd "$(dirname "$0")" && pwd)
IAM_ROLE_CHECK_LIB=1 . "$HERE/iam-role-check.sh"

MISSING=""
ERRORS=""
add_error() { ERRORS="${ERRORS}    - $1: $(printf '%s' "$2" | tr '\n' ' ')
"; }
for svc in $SERVICES; do
  ROLE="${RESOURCE_PREFIX}-cluster-mgmt-${svc}"
  STATE=$(iam_role_state "$ROLE")
  case "$STATE" in
    present) ;;
    missing) MISSING="$MISSING role:$ROLE"; continue ;;
    *) add_error "$ROLE" "${STATE#error: }"; continue ;;
  esac
  if ! ATTACHED=$(aws iam list-attached-role-policies --role-name "$ROLE" \
      --query 'AttachedPolicies[].PolicyArn' --output text 2>&1); then
    add_error "$ROLE (attached policies)" "$ATTACHED"
    continue
  fi
  for arn in $(expected_policies "$svc"); do
    case " $(echo "$ATTACHED" | tr '\t\n' '  ') " in
      *" $arn "*) ;;
      *) MISSING="$MISSING policy:$ROLE:${arn##*/}" ;;
    esac
  done
  # cluster-mgmt-iam carries the customer-managed scoped policy (common/iam/managed-policy.sh),
  # not IAMFullAccess.
  if [ "$svc" = iam ]; then
    SCOPED="${RESOURCE_PREFIX}-cluster-mgmt-iam-scoped"
    case " $(echo "$ATTACHED" | tr '\t\n' '  ') " in
      *":policy/$SCOPED "*) ;;
      *) MISSING="$MISSING policy:$ROLE:$SCOPED" ;;
    esac
  fi
done
# Inline policies apply puts on the eks and rds roles.
for pair in eks:eks-access-management rds:rds-kms; do
  ROLE="${RESOURCE_PREFIX}-cluster-mgmt-${pair%%:*}"
  case "$MISSING$ERRORS" in *"role:$ROLE"*|*"- $ROLE:"*|*"- $ROLE ("*) continue ;; esac
  if ! ERR=$(aws iam get-role-policy --role-name "$ROLE" --policy-name "${pair#*:}" 2>&1 >/dev/null); then
    case "$ERR" in
      *NoSuchEntity*) MISSING="$MISSING inline:$ROLE:${pair#*:}" ;;
      *) add_error "$ROLE (inline ${pair#*:})" "$ERR" ;;
    esac
  fi
done
# Extra roles (arguments) are only checked to exist: the provider's other host-created
# roles (see <provider>:privileged:verify).
for ROLE in "$@"; do
  STATE=$(iam_role_state "$ROLE")
  case "$STATE" in
    present) ;;
    missing) MISSING="$MISSING role:$ROLE" ;;
    *) add_error "$ROLE" "${STATE#error: }" ;;
  esac
done

if [ -n "$ERRORS" ]; then
  echo "✗ could not read the IAM roles (an AWS error, not a missing role):" >&2
  printf '%s' "$ERRORS" >&2
fi
if [ -n "$MISSING" ]; then
  echo "✗ privilegedSteps=external but the IAM roles are not ready:" >&2
  for m in $MISSING; do echo "    - $m" >&2; done
  echo "  They are created by the privileged runner (task privileged:pre). This host does" >&2
  echo "  not create them in external mode." >&2
fi
[ -z "$ERRORS$MISSING" ] || exit 1
echo "✓ cluster-mgmt IAM roles present (verified read-only, privilegedSteps=external)."
