#!/usr/bin/env bash
#
# create-config.sh — Workshop pre-requisite: generate config + create platform ALB + CloudFront
#
# ══════════════════════════════════════════════════════════════════════════════
# OVERVIEW — How to use this workshop
# ══════════════════════════════════════════════════════════════════════════════
#
# This script is the FIRST step. Run it from the workshop/ directory:
#
#   cd workshop
#   ./create-config.sh        # idempotent: skip if valid config exists
#   FORCE=true ./create-config.sh   # overwrite existing config
#
# Then start the workshop installation:
#
#   task install              # from the same workshop/ directory
#
# ══════════════════════════════════════════════════════════════════════════════
# WHAT create-config.sh DOES (in order)
# ══════════════════════════════════════════════════════════════════════════════
#
#  1. Auto-detect AWS environment:
#       - aws.region / aws.accountId       from AWS CLI identity
#       - identityCenter.instanceArn       from IAM Identity Center (waits up to 5min)
#       - identityCenter.adminGroupId      from the "Developers" IDC group
#       - adminRoleName                    from WS_PARTICIPANT_ROLE_ARN or caller identity
#       - clusterProvider                  from CFN stack parameter or CLUSTER_PROVIDER env
#
#  2. Create Platform ALB + CloudFront (when HUB_VPC_ID is set = shared IDE VPC mode):
#       - Creates internal ALB "peeks-hub-platform" in the IDE VPC private subnets
#         via AWS CLI (no aws:cloudformation:* tags → the AWS LBC can adopt it cleanly)
#       - Creates CloudFront VPC Origin pointing to the ALB
#       - Creates CloudFront Distribution → gets domain d*.cloudfront.net
#       - Reserves the CloudFront hostname and writes it to config.local.yaml
#       All steps are IDEMPOTENT — safe to re-run.
#
#  3. Write <repo-root>/config.local.yaml with:
#       - clusterProvider, repo.url/revision, hub.clusterName/version/network
#       - aws.region/accountId
#       - domain: "<CF domain>"  (set by step 2, or empty for non-shared-VPC mode)
#       - insecure: true          (ALB serves HTTP, CloudFront terminates TLS)
#       - identityCenter.*
#       - adminRoleName
#
# ══════════════════════════════════════════════════════════════════════════════
# WHAT task install DOES (in order)
# ══════════════════════════════════════════════════════════════════════════════
#
#  1. gitlab:init-ec2         — Wait for GitLab CE, create root token, create PAT,
#                               create user repos, push initial content, seed
#                               peeks-hub/secrets.git_token with the real PAT
#
#  2. cd platform && task install  — Platform black-box install:
#       a. kind:create           — Create bootstrap Kind cluster (local k8s)
#       b. hub:claim             — Apply EksCluster KRO resource (domainName from config ✅)
#       c. hub:wait-for-eks      — Wait for hub EKS cluster ACTIVE (~20min)
#       d. hub:authorize-ide-access — Add VPC CIDR→cluster-SG :443 (kubectl access)
#       e. hub:seed              — Deploy ArgoCD, ESO, seed cluster secret
#       f. hub:apply-root-appset — Bootstrap ArgoCD ApplicationSets (hub self-managing)
#       g. hub:wait-for-sync     — Wait for hub addons to sync (LBC adopts ALB ✅)
#       h. hub:bootstrap-crossplane-identity — Credential Crossplane providers
#
#  3. set-overlay-repo        — Wire fleet-config GitLab repo into hub ArgoCD cluster secret
#
#  4. spokes:enable-kro × 2  — Declare spoke-dev + spoke-prod in fleet-config overlay
#                               (KRO creates EksclusterWithVpc for each spoke, ~20min)
#
#  5. ray:setup               — Create Ray model S3 bucket, ECR repo, IAM roles, build image
#
#  6. post-install:
#       a. idc:configure      — Configure IDC ↔ Keycloak SAML + SCIM federation
#                               (pre-check: skip if Keycloak unreachable = fast fail)
#       b. setup-env          — Write platform URLs + credentials to ~/.bashrc.d/platform.sh
#
#  7. ray:wait-image + ray:prestage-models — Wait for vLLM image build, stage ML models
#
#  8. wait-for-spokes         — Confirm spoke EKS clusters + ArgoCD apps are ready
#
# ══════════════════════════════════════════════════════════════════════════════
# ENVIRONMENT OVERRIDES
# ══════════════════════════════════════════════════════════════════════════════
#   RESOURCE_PREFIX   (default: from CFN stack or "peeks")
#   CLUSTER_PROVIDER  (default: from CFN parameter or "kind-kro-ack")
#   REPO_URL          (default: https://github.com/aws-samples/appmod-blueprints)
#   REPO_REVISION     (default: $WORKSHOP_GIT_BRANCH)
#   K8S_VERSION       (default: 1.35)
#   FORCE             (default: false) — set to true to overwrite existing config
#   ADMIN_ROLE_NAME   (default: derived from WS_PARTICIPANT_ROLE_ARN or caller identity)
#   HUB_VPC_ID        (default: from CDK bootstrap env) — triggers ALB+CF creation
#   HUB_SUBNET_IDS    (default: from CDK bootstrap env) — private subnet IDs for ALB
#

set -euo pipefail

# Debug trap: log script exit code and last failing command to /tmp/create-config-exit.log
_cc_exit_trap() {
  local code=$?
  local cmd="${BASH_COMMAND:-unknown}"
  echo "[$(date +%H:%M:%S)] create-config.sh exited with code=$code last_cmd='$cmd'" \
    >> /tmp/create-config-exit.log
}
trap '_cc_exit_trap' EXIT

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Source CDK-injected environment variables (HUB_VPC_ID, HUB_SUBNET_IDS, IDE_DOMAIN, etc.)
# These are set by the CDK bootstrap script in /etc/profile.d/workshop.sh but are not
# automatically loaded in non-interactive shells (e.g. SSM RunShellScript, manual runs).
# shellcheck disable=SC1091
[ -f /etc/profile.d/workshop.sh ] && source /etc/profile.d/workshop.sh 2>/dev/null || true

# Fallback: if HUB_VPC_ID still unset, detect the IDE VPC by its CDK name tag.
# CDK creates it with Name="<stackName>/IDE-VPC" — detect by the /IDE-VPC suffix.
if [ -z "${HUB_VPC_ID:-}" ]; then
  _REGION="${AWS_DEFAULT_REGION:-${AWS_REGION:-us-west-2}}"
  HUB_VPC_ID=$(aws ec2 describe-vpcs --region "$_REGION" \
    --filters "Name=tag:Name,Values=*IDE-VPC*" \
    --query 'Vpcs[0].VpcId' --output text 2>/dev/null | grep -v "^None$" || true)
fi
# Fallback: detect private subnets from the IDE VPC (tagged kubernetes.io/role/internal-elb)
if [ -n "${HUB_VPC_ID:-}" ] && [ -z "${HUB_SUBNET_IDS:-}" ]; then
  _REGION="${AWS_DEFAULT_REGION:-${AWS_REGION:-us-west-2}}"
  _SUBS=$(aws ec2 describe-subnets --region "$_REGION" \
    --filters "Name=vpc-id,Values=$HUB_VPC_ID" \
              "Name=tag:kubernetes.io/role/internal-elb,Values=1" \
    --query 'Subnets[].SubnetId' --output text 2>/dev/null | tr '\t' ',' || true)
  [ -n "$_SUBS" ] && HUB_SUBNET_IDS="[$_SUBS]"
fi
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
CLUSTER_PROVIDER="${CLUSTER_PROVIDER:-}"
if [ -z "$CLUSTER_PROVIDER" ]; then
  # Try to read from the CFN stack parameter (set at deploy time by Workshop Studio)
  CLUSTER_PROVIDER=$(aws cloudformation describe-stacks \
    --query "Stacks[?contains(StackName,'peeks-workshop')].Parameters[?ParameterKey=='ClusterProvider'].ParameterValue|[0][0]" \
    --output text 2>/dev/null | grep -v "^None$" || true)
fi
CLUSTER_PROVIDER="${CLUSTER_PROVIDER:-kind-kro-ack}"
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
# ── Reserve the CloudFront hostname (before writing config) ───────────────────
# The platform needs its ingress hostname AT install time (Keycloak realm URLs, the OIDC
# issuer, ingress hosts, ArgoCD/Backstage base URLs). Deriving it from infrastructure the
# install itself creates would be circular, so reserve it up front instead: creating a
# distribution with a placeholder origin returns its *.cloudfront.net name in about a
# second, with no VPC and no load balancer required. `domain` is then an ordinary static
# config value and nothing has to resolve it mid-install.
#
# The real origin is attached AFTER install by scripts/cloudfront-attach-origin.sh, once
# the load balancer controller has created the platform ALB.
echo "[$(date +%H:%M:%S)] ▸ Reserving CloudFront hostname..."
CF_DOMAIN=$(HUB_CLUSTER_NAME="${RESOURCE_PREFIX}-hub" \
  "$REPO_ROOT/scripts/cloudfront-reserve-domain.sh") || CF_DOMAIN=""
if [ -z "$CF_DOMAIN" ]; then
  echo "[$(date +%H:%M:%S)] ERROR: could not reserve a CloudFront hostname." >&2
  echo "                    The platform cannot be installed without a domain." >&2
  exit 1
fi
echo "[$(date +%H:%M:%S)] ✓ Reserved $CF_DOMAIN"

echo "▸ Writing $OUTPUT_FILE ..."
printf 'clusterProvider: "%s"\n' "$CLUSTER_PROVIDER"  >  "$OUTPUT_FILE"
printf 'repo:\n'                                       >> "$OUTPUT_FILE"
printf '  url: "%s"\n'          "$REPO_URL"            >> "$OUTPUT_FILE"
printf '  revision: "%s"\n'     "$REPO_REVISION"       >> "$OUTPUT_FILE"
printf '  basepath: "gitops/"\n'                       >> "$OUTPUT_FILE"
printf 'aws:\n'                                        >> "$OUTPUT_FILE"
printf '  region: "%s"\n'       "$REGION"              >> "$OUTPUT_FILE"
printf '  accountId: "%s"\n'    "$ACCOUNT_ID"          >> "$OUTPUT_FILE"
printf '  profile: "default"\n'                        >> "$OUTPUT_FILE"
# The hostname was reserved above, so it is known here and written as a plain static
# value. insecure=true means the ALB serves HTTP with CloudFront terminating TLS; it also
# makes the platform create the ALB as `internal` with the predictable name
# <cluster>-platform, which is what cloudfront-attach-origin.sh looks for afterwards.
printf 'domain: "%s"\n' "$CF_DOMAIN"                   >> "$OUTPUT_FILE"
printf 'insecure: true\n'                              >> "$OUTPUT_FILE"
printf 'resourcePrefix: "%s"\n' "$RESOURCE_PREFIX"     >> "$OUTPUT_FILE"
printf 'ingressName: ""\n'                             >> "$OUTPUT_FILE"
printf 'ingressSecurityGroups: ""\n'                   >> "$OUTPUT_FILE"

# GitLab/IDE CloudFront domain (separate from the platform CF).
# Available as $CLOUDFRONT_DOMAIN / $IDE_DOMAIN env vars,
# or from the private/git-domain file written by bootstrap.sh.
GIT_DOMAIN="${CLOUDFRONT_DOMAIN:-${IDE_DOMAIN:-}}"
[ -z "$GIT_DOMAIN" ] && [ -f "${REPO_ROOT}/private/git-domain" ] && \
  GIT_DOMAIN="$(cat "${REPO_ROOT}/private/git-domain" | tr -d '[:space:]')"
if [ -n "$GIT_DOMAIN" ]; then
  printf 'gitDomain: "%s"\n' "$GIT_DOMAIN" >> "$OUTPUT_FILE"
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

# --- Platform CloudFront (CloudFront mode only) ------------------------------
# When HUB_VPC_ID is set (shared IDE VPC), create the internal ALB + CloudFront
# distribution NOW so the domain is known before `task install` runs hub:claim.
# hub:claim passes domainName from config, so it must be set here.
# --- Validate --------------------------------------------------------------
echo "[$(date +%H:%M:%S)] ▸ Validating generated YAML..."
yq '.' "$OUTPUT_FILE" >/dev/null

echo "[$(date +%H:%M:%S)] ✓ create-config.sh complete"
echo "    clusterProvider=$CLUSTER_PROVIDER region=$REGION accountId=$ACCOUNT_ID prefix=$RESOURCE_PREFIX"
echo "    clusterName=${RESOURCE_PREFIX}-hub adminRole=$ADMIN_ROLE_NAME"
echo "    idcInstance=$IDC_ARN adminGroupId=${IDC_GROUP:-<empty>}"
echo "    domain=\"$CF_DOMAIN\" (CloudFront, origin not yet attached)"
echo ""
echo "    NEXT: once 'task install' finishes, point CloudFront at the platform ALB:"
echo "      scripts/cloudfront-attach-origin.sh"
