#!/usr/bin/env bash
#
# create-config.sh — Generate config.local.yaml for a CloudFront-mode deployment.
#
# This is a standalone helper (NOT a Taskfile task) because every task in this
# repo reads config.local.yaml at parse time via global vars — so a task cannot
# be used to *create* the file when it does not yet exist.
#
# All values are auto-detected from the current AWS environment:
#   - aws.region / aws.accountId           from the active AWS identity
#   - resourcePrefix / hub.clusterName     from RESOURCE_PREFIX (default "peeks")
#   - identityCenter.instanceArn/group     from IAM Identity Center
#   - adminRoleName                        from the current assumed-role ARN
#
# CloudFront exposure mode is selected by an EMPTY domain (domain: ""). The
# exposure.mode key is intentionally NOT written (removed syntax).
#
# Usage:
#   ./create-config.sh                 # idempotent: skip if valid config exists
#   FORCE=true ./create-config.sh      # overwrite existing config
#
# Optional environment overrides:
#   RESOURCE_PREFIX  (default: peeks)
#   REPO_URL         (default: https://github.com/aws-samples/appmod-blueprints)
#   REPO_REVISION    (default: $WORKSHOP_GIT_BRANCH or feature/cloudfront-on-agent-platform)
#   K8S_VERSION      (default: 1.35)
#   VPC_CIDR         (default: 10.1.0.0/16)
#   CONFIG_FILE      (default: <repo root>/config.local.yaml)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Defaults / overrides --------------------------------------------------
CONFIG_FILE="${CONFIG_FILE:-${SCRIPT_DIR}/config.local.yaml}"
RESOURCE_PREFIX="${RESOURCE_PREFIX:-peeks}"
REPO_URL="${REPO_URL:-https://github.com/aws-samples/appmod-blueprints}"
REPO_REVISION="${REPO_REVISION:-${WORKSHOP_GIT_BRANCH:-feature/cloudfront-on-agent-platform}}"
K8S_VERSION="${K8S_VERSION:-1.35}"
VPC_CIDR="${VPC_CIDR:-10.1.0.0/16}"
FORCE="${FORCE:-false}"

# --- Idempotency -----------------------------------------------------------
if [ "$FORCE" != "true" ] && [ -f "$CONFIG_FILE" ] && yq '.' "$CONFIG_FILE" >/dev/null 2>&1; then
  echo "✓ $CONFIG_FILE already exists and is valid YAML — skipping (use FORCE=true to overwrite)"
  exit 0
fi

# Warn if the revision looks like a release tag (e.g. v1.2.3). The deployment
# expects a branch; a tag usually means WORKSHOP_GIT_BRANCH was left set to a
# release tag in the shell. Override with REPO_REVISION=<branch> if unintended.
if printf '%s' "$REPO_REVISION" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "⚠ repo.revision resolves to release tag '$REPO_REVISION' (from WORKSHOP_GIT_BRANCH)." >&2
  echo "  If you meant a branch, re-run with REPO_REVISION=<branch> ./create-config.sh" >&2
fi

# --- Detect AWS context ----------------------------------------------------
REGION="${AWS_DEFAULT_REGION:-${AWS_REGION:-$(aws configure get region 2>/dev/null || echo us-west-2)}}"

echo "▸ Detecting AWS account..."
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

echo "▸ Detecting IAM Identity Center instance..."
IDC_ARN="$(aws sso-admin list-instances --query 'Instances[0].InstanceArn' --output text --region "$REGION" 2>/dev/null | head -1 | tr -d '[:space:]')"
if [ -z "$IDC_ARN" ] || [ "$IDC_ARN" = "None" ]; then
  echo "✗ No IAM Identity Center instance found in $REGION. Enable IDC before generating config." >&2
  exit 1
fi
IDC_STORE="$(aws sso-admin describe-instance --instance-arn "$IDC_ARN" --query 'IdentityStoreId' --output text --region "$REGION" | head -1 | tr -d '[:space:]')"

echo "▸ Detecting Developers group..."
IDC_GROUP="$(aws identitystore list-groups --identity-store-id "$IDC_STORE" --filters AttributePath=DisplayName,AttributeValue=Developers --query 'Groups[0].GroupId' --output text --region "$REGION" 2>/dev/null | head -1 | tr -d '[:space:]')"
[ "$IDC_GROUP" = "None" ] && IDC_GROUP=""

echo "▸ Detecting admin role name from caller identity..."
CALLER_ARN="$(aws sts get-caller-identity --query Arn --output text)"
ROLE_AFTER="${CALLER_ARN##*role/}"
ADMIN_ROLE_NAME="${ROLE_AFTER%%/*}"
[ -z "$ADMIN_ROLE_NAME" ] && ADMIN_ROLE_NAME="WSParticipantRole"

# --- Write config.local.yaml (printf, never heredoc) -----------------------
echo "▸ Writing $CONFIG_FILE ..."
printf 'clusterProvider: "kind-crossplane"\n'          >  "$CONFIG_FILE"
printf 'repo:\n'                                       >> "$CONFIG_FILE"
printf '  url: "%s"\n'          "$REPO_URL"            >> "$CONFIG_FILE"
printf '  revision: "%s"\n'     "$REPO_REVISION"       >> "$CONFIG_FILE"
printf '  basepath: "gitops/"\n'                       >> "$CONFIG_FILE"
printf 'hub:\n'                                        >> "$CONFIG_FILE"
printf '  clusterName: "%s-hub"\n' "$RESOURCE_PREFIX"  >> "$CONFIG_FILE"
printf '  kubernetesVersion: "%s"\n' "$K8S_VERSION"    >> "$CONFIG_FILE"
printf '  vpcCidr: "%s"\n'      "$VPC_CIDR"            >> "$CONFIG_FILE"
printf '  autoMode: true\n'                            >> "$CONFIG_FILE"
printf 'aws:\n'                                        >> "$CONFIG_FILE"
printf '  region: "%s"\n'       "$REGION"              >> "$CONFIG_FILE"
printf '  accountId: "%s"\n'    "$ACCOUNT_ID"          >> "$CONFIG_FILE"
printf '  profile: "default"\n'                        >> "$CONFIG_FILE"
printf 'domain: ""\n'                                  >> "$CONFIG_FILE"
printf 'resourcePrefix: "%s"\n' "$RESOURCE_PREFIX"     >> "$CONFIG_FILE"
printf 'ingressName: ""\n'                             >> "$CONFIG_FILE"
printf 'ingressSecurityGroups: ""\n'                   >> "$CONFIG_FILE"
printf 'identityCenter:\n'                             >> "$CONFIG_FILE"
printf '  instanceArn: "%s"\n'  "$IDC_ARN"             >> "$CONFIG_FILE"
printf '  region: "%s"\n'       "$REGION"              >> "$CONFIG_FILE"
printf '  adminGroupId: "%s"\n' "$IDC_GROUP"           >> "$CONFIG_FILE"
printf 'argocdCapability:\n'                           >> "$CONFIG_FILE"
printf '  name: "argocd"\n'                            >> "$CONFIG_FILE"
printf 'adminRoleName: "%s"\n'  "$ADMIN_ROLE_NAME"     >> "$CONFIG_FILE"
printf 'modelS3Bucket:\n'                              >> "$CONFIG_FILE"
printf '  enabled: false\n'                            >> "$CONFIG_FILE"

# --- Validate --------------------------------------------------------------
echo "▸ Validating generated YAML..."
yq '.' "$CONFIG_FILE" >/dev/null

echo "✓ config.local.yaml created:"
echo "    region=$REGION accountId=$ACCOUNT_ID prefix=$RESOURCE_PREFIX"
echo "    clusterName=${RESOURCE_PREFIX}-hub adminRole=$ADMIN_ROLE_NAME"
echo "    idcInstance=$IDC_ARN adminGroupId=${IDC_GROUP:-<empty>}"
echo '    domain="" (CloudFront exposure mode)'
