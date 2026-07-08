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
# CloudFront exposure mode: the workshop terminates TLS at CloudFront and the
# platform ALB serves plain HTTP, so we set `insecure: true`. The platform
# CloudFront domain is created by hub:create-platform-cf (running in parallel
# with the platform install) and written to private/cloudfront-domain.
# create-config.sh runs BEFORE the install, so domain is left empty at
# config-generation time — hub:seed reads it lazily from private/cloudfront-domain.
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
#   OUTPUT_FILE      (default: <repo root>/config.local.yaml)
#   ADMIN_ROLE_NAME  (default: derived from WS_PARTICIPANT_ROLE_ARN, else WSParticipantRole)
#                    NOTE: on the IDE, get-caller-identity returns the EC2
#                    instance role (*SharedRole*), which is intentionally
#                    ignored — set ADMIN_ROLE_NAME or WS_PARTICIPANT_ROLE_ARN
#                    to control this explicitly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# This script lives in <repo>/workshop; the config.local.yaml it generates is read
# by the workshop AND the in-place platform at the repo root (SCRIPT_DIR/..).
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# --- Defaults / overrides --------------------------------------------------
# NOTE: deliberately NOT named CONFIG_FILE — the IDE environment exports a
# CONFIG_FILE pointing at the terraform hub-config.yaml, which we do not use
# here. We always target the repo-root config.local.yaml unless OUTPUT_FILE
# is explicitly overridden.
OUTPUT_FILE="${OUTPUT_FILE:-${REPO_ROOT}/config.local.yaml}"
RESOURCE_PREFIX="${RESOURCE_PREFIX:-peeks}"
REPO_URL="${REPO_URL:-https://github.com/aws-samples/appmod-blueprints}"
REPO_REVISION="${REPO_REVISION:-${WORKSHOP_GIT_BRANCH:-feature/cloudfront-on-agent-platform}}"
CLUSTER_PROVIDER="${CLUSTER_PROVIDER:-kind-crossplane}"
K8S_VERSION="${K8S_VERSION:-1.35}"
VPC_CIDR="${VPC_CIDR:-10.1.0.0/16}"
FORCE="${FORCE:-false}"

# --- Idempotency -----------------------------------------------------------
if [ "$FORCE" != "true" ] && [ -f "$OUTPUT_FILE" ] && yq '.' "$OUTPUT_FILE" >/dev/null 2>&1; then
  echo "✓ $OUTPUT_FILE already exists and is valid YAML — skipping (use FORCE=true to overwrite)"
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
# Wait for the IDC instance to appear and become ACTIVE. On a fresh workshop
# account the IDC instance + Developers group are created asynchronously by a
# Lambda, so they may not exist the instant this script runs. Configurable via
# IDC_WAIT_ATTEMPTS (default 30) x IDC_WAIT_INTERVAL seconds (default 10) = 5 min.
IDC_WAIT_ATTEMPTS="${IDC_WAIT_ATTEMPTS:-30}"
IDC_WAIT_INTERVAL="${IDC_WAIT_INTERVAL:-10}"
IDC_ARN=""
i=0
while [ "$i" -lt "$IDC_WAIT_ATTEMPTS" ]; do
  IDC_ARN="$(aws sso-admin list-instances --query 'Instances[0].InstanceArn' --output text --region "$REGION" 2>/dev/null | head -1 | tr -d '[:space:]')"
  [ -n "$IDC_ARN" ] && [ "$IDC_ARN" != "None" ] && break
  echo "  waiting for IDC instance ($i/$IDC_WAIT_ATTEMPTS)..."
  sleep "$IDC_WAIT_INTERVAL"; i=$((i+1))
done
if [ -z "$IDC_ARN" ] || [ "$IDC_ARN" = "None" ]; then
  echo "✗ No IAM Identity Center instance found in $REGION after $((IDC_WAIT_ATTEMPTS * IDC_WAIT_INTERVAL))s. Enable IDC before generating config." >&2
  exit 1
fi
# Wait for the instance to report ACTIVE before querying the identity store.
i=0
while [ "$i" -lt "$IDC_WAIT_ATTEMPTS" ]; do
  IDC_STATUS="$(aws sso-admin describe-instance --instance-arn "$IDC_ARN" --query 'Status' --output text --region "$REGION" 2>/dev/null | tr -d '[:space:]')"
  [ "$IDC_STATUS" = "ACTIVE" ] && break
  echo "  waiting for IDC status ACTIVE (current: ${IDC_STATUS:-unknown}, $i/$IDC_WAIT_ATTEMPTS)..."
  sleep "$IDC_WAIT_INTERVAL"; i=$((i+1))
done
IDC_STORE="$(aws sso-admin describe-instance --instance-arn "$IDC_ARN" --query 'IdentityStoreId' --output text --region "$REGION" | head -1 | tr -d '[:space:]')"

echo "▸ Detecting Developers group..."
# Wait for the Developers group to exist (created asynchronously alongside the instance).
IDC_GROUP=""
i=0
while [ "$i" -lt "$IDC_WAIT_ATTEMPTS" ]; do
  IDC_GROUP="$(aws identitystore list-groups --identity-store-id "$IDC_STORE" --filters AttributePath=DisplayName,AttributeValue=Developers --query 'Groups[0].GroupId' --output text --region "$REGION" 2>/dev/null | head -1 | tr -d '[:space:]')"
  [ -n "$IDC_GROUP" ] && [ "$IDC_GROUP" != "None" ] && break
  echo "  waiting for Developers group ($i/$IDC_WAIT_ATTEMPTS)..."
  sleep "$IDC_WAIT_INTERVAL"; i=$((i+1))
done
[ "$IDC_GROUP" = "None" ] && IDC_GROUP=""

echo "▸ Detecting admin role name..."
# Priority order for the admin role name:
#   1. ADMIN_ROLE_NAME env override (explicit)
#   2. WS_PARTICIPANT_ROLE_ARN env (set by the workshop bootstrap from the
#      ParticipantAssumedRoleArn CFN parameter) — this is the participant role
#   3. Caller identity ARN — but only if it is NOT the EC2 instance/shared role
#      (on the IDE, get-caller-identity returns the instance role, e.g.
#      *SharedRole*, which is NOT the admin role we want)
#   4. Fallback: WSParticipantRole
arn_to_role() { local a="$1"; local r="${a##*role/}"; printf '%s' "${r%%/*}"; }

ADMIN_ROLE_NAME="${ADMIN_ROLE_NAME:-}"
if [ -z "$ADMIN_ROLE_NAME" ] && [ -n "${WS_PARTICIPANT_ROLE_ARN:-}" ]; then
  ADMIN_ROLE_NAME="$(arn_to_role "$WS_PARTICIPANT_ROLE_ARN")"
fi
if [ -z "$ADMIN_ROLE_NAME" ]; then
  CALLER_ARN="$(aws sts get-caller-identity --query Arn --output text)"
  CANDIDATE="$(arn_to_role "$CALLER_ARN")"
  # Reject the EC2 instance/shared role — it is not the participant admin role.
  case "$CANDIDATE" in
    *SharedRole*|*-team-stack-*|"") ;;  # ignore instance role
    *) ADMIN_ROLE_NAME="$CANDIDATE" ;;
  esac
fi
[ -z "$ADMIN_ROLE_NAME" ] && ADMIN_ROLE_NAME="WSParticipantRole"

# --- Write config.local.yaml (printf, never heredoc) -----------------------
echo "▸ Writing $OUTPUT_FILE ..."
printf 'clusterProvider: "%s"\n' "$CLUSTER_PROVIDER"  >  "$OUTPUT_FILE"
printf 'repo:\n'                                       >> "$OUTPUT_FILE"
printf '  url: "%s"\n'          "$REPO_URL"            >> "$OUTPUT_FILE"
printf '  revision: "%s"\n'     "$REPO_REVISION"       >> "$OUTPUT_FILE"
printf '  basepath: "gitops/"\n'                       >> "$OUTPUT_FILE"
printf 'hub:\n'                                        >> "$OUTPUT_FILE"
printf '  clusterName: "%s-hub"\n' "$RESOURCE_PREFIX"  >> "$OUTPUT_FILE"
printf '  kubernetesVersion: "%s"\n' "$K8S_VERSION"    >> "$OUTPUT_FILE"
printf '  vpcCidr: "%s"\n'      "$VPC_CIDR"            >> "$OUTPUT_FILE"
printf '  autoMode: true\n'                            >> "$OUTPUT_FILE"
printf 'aws:\n'                                        >> "$OUTPUT_FILE"
printf '  region: "%s"\n'       "$REGION"              >> "$OUTPUT_FILE"
printf '  accountId: "%s"\n'    "$ACCOUNT_ID"          >> "$OUTPUT_FILE"
printf '  profile: "default"\n'                        >> "$OUTPUT_FILE"
# domain is always empty at config-generation time.
# hub:create-platform-cf writes the real CF domain to private/cloudfront-domain
# and hub:seed reads it from there (lazy resolution, not from config).
DOMAIN_VALUE=""
printf 'domain: "%s"\n' "$DOMAIN_VALUE"                >> "$OUTPUT_FILE"
printf 'insecure: true\n'                              >> "$OUTPUT_FILE"
printf 'resourcePrefix: "%s"\n' "$RESOURCE_PREFIX"     >> "$OUTPUT_FILE"
printf 'ingressName: ""\n'                             >> "$OUTPUT_FILE"
printf 'ingressSecurityGroups: ""\n'                   >> "$OUTPUT_FILE"

# GitLab/IDE CloudFront domain (separate from the platform CF).
# Available as $CLOUDFRONT_DOMAIN / $IDE_DOMAIN env vars,
# or from the private/gitlab-cloudfront-domain file written by bootstrap.sh.
GITLAB_CF_DOMAIN="${CLOUDFRONT_DOMAIN:-${IDE_DOMAIN:-}}"
[ -z "$GITLAB_CF_DOMAIN" ] && [ -f "${REPO_ROOT}/private/gitlab-cloudfront-domain" ] && \
  GITLAB_CF_DOMAIN="$(cat "${REPO_ROOT}/private/gitlab-cloudfront-domain" | tr -d '[:space:]')"
if [ -n "$GITLAB_CF_DOMAIN" ]; then
  printf 'cloudfront:\n'                               >> "$OUTPUT_FILE"
  printf '  gitlabDomain: "%s"\n' "$GITLAB_CF_DOMAIN" >> "$OUTPUT_FILE"
fi
printf 'identityCenter:\n'                             >> "$OUTPUT_FILE"
printf '  instanceArn: "%s"\n'  "$IDC_ARN"             >> "$OUTPUT_FILE"
printf '  region: "%s"\n'       "$REGION"              >> "$OUTPUT_FILE"
printf '  adminGroupId: "%s"\n' "$IDC_GROUP"           >> "$OUTPUT_FILE"
printf 'argocdCapability:\n'                           >> "$OUTPUT_FILE"
printf '  name: "argocd"\n'                            >> "$OUTPUT_FILE"
printf 'adminRoleName: "%s"\n'  "$ADMIN_ROLE_NAME"     >> "$OUTPUT_FILE"
# Hub network: when CDK provides VPC/subnet IDs, the hub uses an existing VPC
# (EksCluster RGD) instead of creating its own (EksClusterWithVpc).
if [ -n "${HUB_VPC_ID:-}" ] && [ -n "${HUB_SUBNET_IDS:-}" ]; then
  # HUB_SUBNET_IDS comes as "['subnet-xxx','subnet-yyy','subnet-zzz']" from CDK
  # Parse into individual subnet IDs
  SUBNETS=$(echo "$HUB_SUBNET_IDS" | tr -d "[]'" | tr ',' '\n')
  SUBNET1=$(echo "$SUBNETS" | sed -n '1p')
  SUBNET2=$(echo "$SUBNETS" | sed -n '2p')
  SUBNET3=$(echo "$SUBNETS" | sed -n '3p')
  printf 'hub:\n'                                      >> "$OUTPUT_FILE"
  printf '  clusterName: "%s-hub"\n' "$RESOURCE_PREFIX" >> "$OUTPUT_FILE"
  printf '  kubernetesVersion: "%s"\n' "$K8S_VERSION"  >> "$OUTPUT_FILE"
  printf '  autoMode: true\n'                          >> "$OUTPUT_FILE"
  printf '  network:\n'                                >> "$OUTPUT_FILE"
  printf '    vpcId: "%s"\n' "$HUB_VPC_ID"             >> "$OUTPUT_FILE"
  printf '    subnetIds:\n'                            >> "$OUTPUT_FILE"
  printf '      - "%s"\n' "$SUBNET1"                   >> "$OUTPUT_FILE"
  printf '      - "%s"\n' "$SUBNET2"                   >> "$OUTPUT_FILE"
  if [ -n "$SUBNET3" ]; then
    printf '      - "%s"\n' "$SUBNET3"                 >> "$OUTPUT_FILE"
  fi
else
  printf 'hub:\n'                                      >> "$OUTPUT_FILE"
  printf '  clusterName: "%s-hub"\n' "$RESOURCE_PREFIX" >> "$OUTPUT_FILE"
  printf '  kubernetesVersion: "%s"\n' "$K8S_VERSION"  >> "$OUTPUT_FILE"
  printf '  vpcCidr: "%s"\n'      "$VPC_CIDR"          >> "$OUTPUT_FILE"
  printf '  autoMode: true\n'                          >> "$OUTPUT_FILE"
fi
printf 'modelS3Bucket:\n'                              >> "$OUTPUT_FILE"
printf '  enabled: false\n'                            >> "$OUTPUT_FILE"

# --- Validate --------------------------------------------------------------
echo "▸ Validating generated YAML..."
yq '.' "$OUTPUT_FILE" >/dev/null

echo "✓ config.local.yaml created:"
echo "    clusterProvider=$CLUSTER_PROVIDER region=$REGION accountId=$ACCOUNT_ID prefix=$RESOURCE_PREFIX"
echo "    clusterName=${RESOURCE_PREFIX}-hub adminRole=$ADMIN_ROLE_NAME"
echo "    idcInstance=$IDC_ARN adminGroupId=${IDC_GROUP:-<empty>}"
echo "    domain=\"\" (CloudFront exposure mode) cloudfrontDomain=${CF_DOMAIN:-<not detected>}"
