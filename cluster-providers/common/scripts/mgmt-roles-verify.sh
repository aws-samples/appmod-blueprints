#!/bin/sh
# Read-only check of the <prefix>-cluster-mgmt-* IAM roles that `hub:create-mgmt-roles`
# creates. Used when config.yaml sets `privilegedSteps: external`: a separate, more
# privileged runner (e.g. a CodeBuild project running `task privileged:pre`) created the
# roles, and the install host only needs iam:GetRole / ListAttachedRolePolicies /
# GetRolePolicy (all in the AWS ReadOnlyAccess managed policy) to confirm they are there.
#
# Fails (exit 1) listing every missing role/policy, so an install that depends on the
# external runner stops at once instead of leaving ACK stuck on "data pending" later.
# A service with a pre-created role (hub.iam.clusterMgmtRoleArns.<service> in CONFIG_FILE,
# kind-kro-ack only: kind-crossplane does not pass CONFIG_FILE)
# is only checked to exist: apply puts no policy on such a role, the consumer owns them.
# Keep SERVICES / expected_policies in sync with get_policies() in
# cluster-providers/kind-{kro-ack,crossplane}/Taskfile.yaml (hub:create-mgmt-roles:apply);
# workshop/scripts/tests/test_privileged_offload.py enforces it.
set -eu

: "${RESOURCE_PREFIX:?RESOURCE_PREFIX is required}"
SERVICES="ec2 eks iam ecr s3 dynamodb secretsmanager rds"
HERE=$(cd "$(dirname "$0")" && pwd)

# Services whose role the consumer pre-created (same key apply reads).
BYO=""
if [ -n "${CONFIG_FILE:-}" ] && [ -f "$CONFIG_FILE" ]; then
  for svc in $SERVICES; do
    ARN=$(yq ".hub.iam.clusterMgmtRoleArns.$svc // \"\"" "$CONFIG_FILE" 2>/dev/null || true)
    if [ -n "$ARN" ] && [ "$ARN" != null ]; then BYO="$BYO $svc"; fi
  done
fi
is_byo() { case " $BYO " in *" $1 "*) return 0;; esac; return 1; }

expected_policies() {
  case $1 in
    ec2) echo "arn:aws:iam::aws:policy/AmazonEC2FullAccess arn:aws:iam::aws:policy/AmazonVPCFullAccess";;
    eks) echo "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy arn:aws:iam::aws:policy/AmazonEKSServicePolicy arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly";;
    iam) echo "";;  # no AWS managed policy: <prefix>-cluster-mgmt-iam-scoped, checked below
    ecr) echo "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryFullAccess";;
    s3) echo "arn:aws:iam::aws:policy/AmazonS3FullAccess";;
    dynamodb) echo "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess";;
    secretsmanager) echo "arn:aws:iam::aws:policy/SecretsManagerReadWrite";;
    rds) echo "arn:aws:iam::aws:policy/AmazonRDSFullAccess arn:aws:iam::aws:policy/SecretsManagerReadWrite";;
  esac
}

MISSING=""
for svc in $SERVICES; do
  ROLE="${RESOURCE_PREFIX}-cluster-mgmt-${svc}"
  if ! aws iam get-role --role-name "$ROLE" --query 'Role.RoleName' --output text >/dev/null 2>&1; then
    MISSING="$MISSING role:$ROLE"
    continue
  fi
  is_byo "$svc" && continue
  ATTACHED=$(aws iam list-attached-role-policies --role-name "$ROLE" \
    --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null || echo "")
  for arn in $(expected_policies "$svc"); do
    case " $(echo "$ATTACHED" | tr '\t\n' '  ') " in
      *" $arn "*) ;;
      *) MISSING="$MISSING policy:$ROLE:${arn##*/}" ;;
    esac
  done
  # cluster-mgmt-iam carries the customer-managed scoped policy (common/iam/managed-policy.sh),
  # not IAMFullAccess.
  if [ "$svc" = iam ]; then
    SCOPED=$(sh "$HERE/../iam/managed-policy.sh" name "$RESOURCE_PREFIX" "$ROLE")
    case " $(echo "$ATTACHED" | tr '\t\n' '  ') " in
      *":policy/$SCOPED "*) ;;
      *) MISSING="$MISSING policy:$ROLE:$SCOPED" ;;
    esac
  fi
done
# Inline policies apply puts on the eks and rds roles.
for pair in eks:eks-access-management rds:rds-kms; do
  ROLE="${RESOURCE_PREFIX}-cluster-mgmt-${pair%%:*}"
  is_byo "${pair%%:*}" && continue
  case "$MISSING" in *"role:$ROLE"*) continue ;; esac
  aws iam get-role-policy --role-name "$ROLE" --policy-name "${pair#*:}" >/dev/null 2>&1 \
    || MISSING="$MISSING inline:$ROLE:${pair#*:}"
done

if [ -n "$MISSING" ]; then
  echo "✗ privilegedSteps=external but the cluster-mgmt IAM roles are not ready:" >&2
  for m in $MISSING; do echo "    - $m" >&2; done
  echo "  They are created by the privileged runner (task privileged:pre, e.g. the" >&2
  echo "  InstallOffload CodeBuild project). This host does not create them in external mode." >&2
  exit 1
fi
echo "✓ cluster-mgmt IAM roles present (verified read-only, privilegedSteps=external)."
