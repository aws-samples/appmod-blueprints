#!/bin/sh
# Read-only check of the <prefix>-cluster-mgmt-* IAM roles that `hub:create-mgmt-roles`
# creates, plus any role named as an argument (existence only). Used when config.yaml
# sets `privilegedSteps: external`: a separate, more privileged runner (e.g. a CodeBuild
# project running `task privileged:pre`) created the roles, and the install host only needs
# iam:GetRole / ListAttachedRolePolicies / GetRolePolicy, plus iam:GetPolicy /
# GetPolicyVersion to read the cluster-mgmt-iam scoped policy (all in the AWS ReadOnlyAccess
# managed policy) to confirm they are there.
#
# Fails (exit 1) listing every missing role/policy, so an install that depends on the
# external runner stops at once instead of leaving ACK stuck on "data pending" later.
# Keep SERVICES / expected_policies in sync with get_policies() in
# cluster-providers/kind-{kro-ack,crossplane}/Taskfile.yaml (hub:create-mgmt-roles:apply);
# workshop/scripts/tests/test_privileged_offload.py enforces it.
#
# Optional environment:
#   BYO_SERVICES   services whose cluster-mgmt role the consumer brings
#                  (hub.iam.clusterMgmtRoleArns): checked to exist only, since the inline
#                  path attaches nothing to them either.
#   SCOPED_ROLES   roles that must also carry their scoped customer-managed policy
#                  (common/iam/managed-policy.sh), e.g. <hub>-crossplane-provider.
#   MGMT_SERVICES  the cluster-mgmt services to check (default: all; empty: none).
#   LEGACY_DETACH  "runner" (default): privileged:pre detaches the policies older installs
#                  attached; "manual": the provider does not (kind-crossplane).
set -eu

: "${RESOURCE_PREFIX:?RESOURCE_PREFIX is required}"
SERVICES="${MGMT_SERVICES-ec2 eks iam ecr s3 dynamodb secretsmanager rds}"
BYO_SERVICES="${BYO_SERVICES:-}"
is_byo() { case " $BYO_SERVICES " in *" $1 "*) return 0 ;; esac; return 1; }

# Same naming rule as policy_name() in common/iam/managed-policy.sh: "<role>-scoped", with
# "<prefix>-" in front when the role name does not start with it.
scoped_name() {
  case "$1" in
    "$RESOURCE_PREFIX"-*) echo "$1-scoped" ;;
    *) echo "$RESOURCE_PREFIX-$1-scoped" ;;
  esac
}
# has_scoped <attached arns> <base>: managed-policy.sh names a replacement <base>-<8 hex
# digits> after a document change.
has_scoped() { echo "$1" | tr '\t' '\n' | grep -Eq ":policy/$2(-[0-9a-f]{8})?\$"; }

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
WARNINGS=""
NOGUARD=""
UNREADABLE=""
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
  # A bring-your-own role is used as is (no policy) by the inline path too.
  is_byo "$svc" && continue
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
    has_scoped "$ATTACHED" "$SCOPED" || MISSING="$MISSING policy:$ROLE:$SCOPED"
    # Read-only content check: the attached scoped policy must carry the attach Deny
    # (cluster-providers/common/iam/cluster-mgmt-iam-policy.json). Warning only, so an
    # existing hub is told to re-run the runner instead of failing the install.
    SCOPED_ARN=$(echo "$ATTACHED" | tr '\t' '\n' | grep -E ":policy/$SCOPED(-[0-9a-f]{8})?\$" | head -n 1 || true)
    if [ -n "$SCOPED_ARN" ]; then
      if VID=$(aws iam get-policy --policy-arn "$SCOPED_ARN" --query Policy.DefaultVersionId --output text 2>/dev/null) &&
         DOC=$(aws iam get-policy-version --policy-arn "$SCOPED_ARN" --version-id "$VID" --query PolicyVersion.Document --output json 2>/dev/null); then
        case "$DOC" in
          *DenyAttachAwsManagedPolicyOutsideAllowlist*) ;;
          *) NOGUARD="$NOGUARD $ROLE" ;;
        esac
      else
        UNREADABLE="$UNREADABLE $ROLE"
      fi
    fi
    case "$ATTACHED" in *policy/IAMFullAccess*)
      WARNINGS="$WARNINGS $ROLE:IAMFullAccess" ;;
    esac
  fi
done
# Inline policies apply puts on the eks and rds roles.
for pair in eks:eks-access-management rds:rds-kms; do
  case " $SERVICES " in *" ${pair%%:*} "*) ;; *) continue ;; esac
  is_byo "${pair%%:*}" && continue
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

# Roles with a scoped customer-managed policy (privileged:pre attaches it and detaches
# AdministratorAccess). A missing scoped policy means privileged:pre did not run from this
# revision.
for ROLE in ${SCOPED_ROLES:-}; do
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
  SCOPED=$(scoped_name "$ROLE")
  has_scoped "$ATTACHED" "$SCOPED" || MISSING="$MISSING policy:$ROLE:$SCOPED"
  case "$ATTACHED" in *policy/AdministratorAccess*)
    WARNINGS="$WARNINGS $ROLE:AdministratorAccess" ;;
  esac
done

# Not a failure: verify checks that the required policies are there, and only the runner
# (task privileged:pre) detaches the ones older installs attached.
for w in $WARNINGS; do
  if [ "${LEGACY_DETACH:-runner}" = manual ]; then
    echo "  ⚠ ${w%%:*} still has ${w#*:} attached (from an older install); this provider does not detach it, detach it manually" >&2
  else
    echo "  ⚠ ${w%%:*} still has ${w#*:} attached (from an older install); re-run task privileged:pre on the runner to detach it" >&2
  fi
done
for r in $NOGUARD; do
  echo "  ⚠ $r scoped policy has no DenyAttachAwsManagedPolicyOutsideAllowlist statement (older install); re-run task privileged:pre on the runner to update it" >&2
done
for r in $UNREADABLE; do
  echo "  ⚠ $r: could not read the scoped policy (needs iam:GetPolicy and iam:GetPolicyVersion), so its DenyAttachAwsManagedPolicyOutsideAllowlist statement was not checked" >&2
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
echo "✓ IAM roles and policies present (verified read-only, privilegedSteps=external)."
