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
#       - Writes domain to config.local.yaml and private/cloudfront-domain
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

# --- Platform CloudFront (CloudFront mode only) ------------------------------
# When HUB_VPC_ID is set (shared IDE VPC), create the internal ALB + CloudFront
# distribution NOW so the domain is known before `task install` runs hub:claim.
# hub:claim passes domainName from config, so it must be set here.
# ── Platform ALB + CloudFront (parallel with IDC detection above) ─────────────
# We launch ALB+VPC Origin creation in the BACKGROUND (before IDC detection) so
# the ~8min VPC Origin deploy overlaps with the ~2min IDC polling. Then after
# config is written, we wait for the VPC Origin, create the CF distribution
# (domain known immediately), and update the config with the domain.
#
# Timeline:
#   t=0   start_platform_infra() in background  ─┐
#   t=0   IDC detection / admin role (~2min)      │ parallel
#   t=2   write config.local.yaml                 │
#   t~8   VPC Origin Deployed ←────────────────── ┘
#   t~8   create CF distribution → CF_DOMAIN known
#   t~8   update config domain, write cloudfront-domain
#   t~8   task install begins (hub:claim gets correct domainName)

# Use fixed /tmp paths so background subshell can write and main shell can read.
# A mktemp dir would require export and subshell inheritance which is fragile.
_PLATFORM_INFRA_DIR="/tmp/create-config-infra-$$"
mkdir -p "$_PLATFORM_INFRA_DIR"
_VPC_ORIGIN_FILE="$_PLATFORM_INFRA_DIR/vpc-origin-id.txt"
_ALB_ARN_FILE="$_PLATFORM_INFRA_DIR/alb-arn.txt"
_INFRA_LOG="/tmp/create-config-infra.log"
_INFRA_PID_FILE="$_PLATFORM_INFRA_DIR/pid.txt"

CF_DOMAIN=""

if [ -n "${HUB_VPC_ID:-}" ]; then

  # ── Background function: create ALB SG + ALB + VPC Origin ─────────────────
  _start_platform_infra() {
    set -euo pipefail
    exec >> "$_INFRA_LOG" 2>&1
    REGION="$1"; HUB_VPC_ID="$2"; HUB_SUBNET_IDS="$3"
    HUB_CLUSTER_NAME="${RESOURCE_PREFIX:-peeks}-hub"
    ALB_NAME="${HUB_CLUSTER_NAME}-platform"

    # Wait for pre-requisites (VPC + subnets)
    echo "[$(date +%H:%M:%S)] Waiting for pre-requisites..."
    for _i in $(seq 1 30); do
      [ -f /etc/profile.d/workshop.sh ] || { sleep 10; continue; }
      _vpc=$(aws ec2 describe-vpcs --vpc-ids "$HUB_VPC_ID" --region "$REGION" \
        --query 'Vpcs[0].VpcId' --output text 2>/dev/null || echo "")
      [ -z "$_vpc" ] || [ "$_vpc" = "None" ] && { sleep 10; continue; }
      break
    done
    echo "[$(date +%H:%M:%S)] Pre-requisites ready"

    VPC_CIDR=$(aws ec2 describe-vpcs --vpc-ids "$HUB_VPC_ID" --region "$REGION" \
      --query 'Vpcs[0].CidrBlock' --output text 2>/dev/null)

    # ALB SG
    SG_NAME="${HUB_CLUSTER_NAME}-platform-alb-sg"
    SG_ID=$(aws ec2 describe-security-groups \
      --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$HUB_VPC_ID" \
      --region "$REGION" --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null)
    [ "$SG_ID" = "None" ] && SG_ID=""
    if [ -z "$SG_ID" ]; then
      SG_ID=$(aws ec2 create-security-group \
        --group-name "$SG_NAME" \
        --description "Platform ALB (internal, CloudFront VPC Origin)" \
        --vpc-id "$HUB_VPC_ID" --region "$REGION" \
        --query 'GroupId' --output text 2>/dev/null) || \
      SG_ID=$(aws ec2 describe-security-groups \
        --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$HUB_VPC_ID" \
        --region "$REGION" --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null)
      aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
        --protocol tcp --port 80 --cidr "$VPC_CIDR" --region "$REGION" >/dev/null 2>&1 || true
    fi
    echo "[$(date +%H:%M:%S)] ALB SG: $SG_ID"

    # Subnets
    PRIVATE_SUBNETS=""
    echo "[$(date +%H:%M:%S)] DEBUG: HUB_SUBNET_IDS='${HUB_SUBNET_IDS:-}' HUB_VPC_ID='$HUB_VPC_ID'"
    if [ -n "${HUB_SUBNET_IDS:-}" ]; then
      PRIVATE_SUBNETS=$(echo "$HUB_SUBNET_IDS" | tr -d "[]'" | tr ',' ' ')
      echo "[$(date +%H:%M:%S)] DEBUG: Subnets from HUB_SUBNET_IDS: $PRIVATE_SUBNETS"
    fi
    if [ -z "$PRIVATE_SUBNETS" ]; then
      echo "[$(date +%H:%M:%S)] DEBUG: Falling back to tag lookup for subnets..."
      PRIVATE_SUBNETS=$(aws ec2 describe-subnets \
        --filters "Name=vpc-id,Values=$HUB_VPC_ID" \
                  "Name=tag:kubernetes.io/role/internal-elb,Values=1" \
        --region "$REGION" \
        --query 'Subnets[].[SubnetId,AvailabilityZone]' --output text 2>/dev/null | \
        sort -k2 -u | awk '{print $1}' | tr '\n' ' ')
      echo "[$(date +%H:%M:%S)] DEBUG: Subnets from tag lookup: '${PRIVATE_SUBNETS}'"
    fi
    [ -z "$PRIVATE_SUBNETS" ] && { echo "ERROR: no subnets found (HUB_SUBNET_IDS empty and tag lookup returned nothing)"; exit 1; }

    # Tag subnets
    for _sn in $PRIVATE_SUBNETS; do
      aws ec2 create-tags --resources "$_sn" --region "$REGION" \
        --tags Key=kubernetes.io/role/internal-elb,Value=1 >/dev/null 2>&1 || true
    done

    # ALB
    echo "[$(date +%H:%M:%S)] DEBUG: Subnets final: $PRIVATE_SUBNETS"
    ALB_ARN=$(aws elbv2 describe-load-balancers --names "$ALB_NAME" \
      --region "$REGION" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null) || ALB_ARN=""
    [ "$ALB_ARN" = "None" ] && ALB_ARN=""
    echo "[$(date +%H:%M:%S)] DEBUG: Existing ALB_ARN='$ALB_ARN'"
    if [ -z "$ALB_ARN" ]; then
      ALB_ARN=$(aws elbv2 create-load-balancer \
        --name "$ALB_NAME" --subnets $PRIVATE_SUBNETS \
        --security-groups "$SG_ID" --scheme internal --type application \
        --tags Key=elbv2.k8s.aws/cluster,Value="$HUB_CLUSTER_NAME" \
               Key=ingress.k8s.aws/stack,Value=platform \
               Key=ingress.k8s.aws/resource,Value=LoadBalancer \
        --region "$REGION" \
        --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null) || true
      if [ -z "$ALB_ARN" ] || [ "$ALB_ARN" = "None" ]; then
        ALB_ARN=$(aws elbv2 describe-load-balancers --names "$ALB_NAME" \
          --region "$REGION" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null)
        [ "$ALB_ARN" = "None" ] && ALB_ARN=""
      fi
      [ -z "$ALB_ARN" ] && { echo "ERROR: ALB creation failed"; exit 1; }
      aws elbv2 create-listener --load-balancer-arn "$ALB_ARN" --protocol HTTP --port 80 \
        --default-actions "Type=fixed-response,FixedResponseConfig={MessageBody=Not Found,StatusCode=404,ContentType=text/plain}" \
        --region "$REGION" >/dev/null 2>&1 || true
    fi
    echo "[$(date +%H:%M:%S)] ALB: $ALB_ARN"
    echo -n "$ALB_ARN" > "$_ALB_ARN_FILE"

    # VPC Origin
    VPC_ORIGIN_NAME="${HUB_CLUSTER_NAME}-platform-vpc-origin"
    VPC_ORIGIN_ID=$(aws cloudfront list-vpc-origins \
      --query "VpcOriginList.Items[?Name=='$VPC_ORIGIN_NAME'].Id" \
      --output text 2>/dev/null | tr -d '[:space:]')
    [ "$VPC_ORIGIN_ID" = "None" ] && VPC_ORIGIN_ID=""
    if [ -z "$VPC_ORIGIN_ID" ]; then
      VPC_ORIGIN_ID=$(aws cloudfront create-vpc-origin \
        --vpc-origin-endpoint-config "{
          \"Name\": \"$VPC_ORIGIN_NAME\",
          \"Arn\": \"$ALB_ARN\",
          \"HTTPPort\": 80,
          \"HTTPSPort\": 443,
          \"OriginProtocolPolicy\": \"http-only\",
          \"OriginSslProtocols\": {\"Quantity\": 1, \"Items\": [\"TLSv1.2\"]}
        }" --query 'VpcOrigin.Id' --output text 2>/dev/null)
    fi
    echo "[$(date +%H:%M:%S)] VPC Origin: $VPC_ORIGIN_ID (waiting for Deployed...)"
    echo -n "$VPC_ORIGIN_ID" > "$_VPC_ORIGIN_FILE"

    # Start CF distribution creation immediately — don't wait for VPC Origin Deployed.
    # AWS accepts a CF distribution with a VPC Origin still Deploying.
    # CF and VPC Origin deployment overlap (~8min each) saving ~8min total.
    # Check if CF already exists (idempotency)
    _CF_COMMENT="${RESOURCE_PREFIX}-hub-platform"
    _CF_DOMAIN_EXISTING=$(aws cloudfront list-distributions \
      --query "DistributionList.Items[?Comment=='${_CF_COMMENT}'].DomainName | [0]" \
      --output text 2>/dev/null | tr -d '[:space:]')
    [ "$_CF_DOMAIN_EXISTING" = "None" ] && _CF_DOMAIN_EXISTING=""
    if [ -n "$_CF_DOMAIN_EXISTING" ]; then
      echo "[$(date +%H:%M:%S)] ↻ Reusing CloudFront: $_CF_DOMAIN_EXISTING"
      echo -n "$_CF_DOMAIN_EXISTING" > "${_PLATFORM_INFRA_DIR}/cf-domain.txt"
    fi

    # Wait for VPC Origin Deployed (CF requires Deployed state)
    for _i in $(seq 1 60); do
      STATE=$(aws cloudfront get-vpc-origin --id "$VPC_ORIGIN_ID" \
        --query 'VpcOrigin.Status' --output text 2>/dev/null || echo "Pending")
      [ "$STATE" = "Deployed" ] && break
      [ $((${_i:-0} % 4)) -eq 0 ] && echo "[$(date +%H:%M:%S)] VPC Origin ${_i}x15s: $STATE"
      sleep 15
    done
    [ "$STATE" != "Deployed" ] && { echo "ERROR: VPC Origin not Deployed"; exit 1; }
    echo "[$(date +%H:%M:%S)] VPC Origin Deployed: $VPC_ORIGIN_ID"
    echo -n "$VPC_ORIGIN_ID" > "$_VPC_ORIGIN_FILE"
  }
  export -f _start_platform_infra
  export _PLATFORM_INFRA_DIR _VPC_ORIGIN_FILE _ALB_ARN_FILE _INFRA_LOG RESOURCE_PREFIX

  # Check idempotency first — if CF already exists, no need for background job
  _CF_COMMENT="${RESOURCE_PREFIX}-hub-platform"
  CF_DOMAIN=$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?Comment=='${_CF_COMMENT}'].DomainName | [0]" \
    --output text 2>/dev/null | tr -d '[:space:]')
  [ "$CF_DOMAIN" = "None" ] && CF_DOMAIN=""

  if [ -n "$CF_DOMAIN" ]; then
    echo "  ↻ Reusing CloudFront: $CF_DOMAIN (skipping background infra)"
    # Write domain to config immediately — same as new creation path
    yq -i ".domain = \"$CF_DOMAIN\"" "$OUTPUT_FILE" 2>/dev/null || \
      sed -i "s|domain: .*|domain: \"$CF_DOMAIN\"|" "$OUTPUT_FILE"
    mkdir -p "$(dirname "$OUTPUT_FILE")/../private"
    echo -n "$CF_DOMAIN" > "$(dirname "$OUTPUT_FILE")/../private/cloudfront-domain"
    echo "  ✓ domain written to config: $CF_DOMAIN"
  else
    echo "  ▸ Starting ALB+VPC Origin creation in background..."
    bash -c '_start_platform_infra "$@"' _ "$REGION" "$HUB_VPC_ID" "${HUB_SUBNET_IDS:-}" &
    _INFRA_PID=$!
    echo "$_INFRA_PID" > "$_INFRA_PID_FILE"
    echo "  ▸ Background PID=$_INFRA_PID (VPC Origin deploys while IDC is detected)"
  fi

fi  # end HUB_VPC_ID block — will rejoin after config is written


# ── Rejoin background platform infra (if started) ─────────────────────────
if [ -n "${HUB_VPC_ID:-}" ] && [ -n "${CF_DOMAIN:-}" ]; then
  : # CF already existed, nothing to do
elif [ -n "${HUB_VPC_ID:-}" ] && [ -f "${_INFRA_PID_FILE:-/dev/null}" ]; then
  _INFRA_PID=$(cat "$_INFRA_PID_FILE" 2>/dev/null)
  if [ -n "$_INFRA_PID" ]; then
    echo "  ▸ Waiting for background VPC Origin to finish..."
    # Stream infra log to stdout in real time
    tail -f "$_INFRA_LOG" 2>/dev/null &
    _TAIL_PID=$!
    if wait "$_INFRA_PID" 2>/dev/null; then
      kill "$_TAIL_PID" 2>/dev/null; wait "$_TAIL_PID" 2>/dev/null
      echo "  ✓ Background infra completed"
    else
      kill "$_TAIL_PID" 2>/dev/null; wait "$_TAIL_PID" 2>/dev/null
      echo "  ✗ Background infra failed — check $_INFRA_LOG"
      exit 1
    fi
  fi

  VPC_ORIGIN_ID=$(cat "$_VPC_ORIGIN_FILE" 2>/dev/null || echo "")
  ALB_ARN=$(cat "$_ALB_ARN_FILE" 2>/dev/null || echo "")

  # CF domain written by background job (created in parallel with VPC Origin wait)
  CF_DOMAIN=$(cat "${_PLATFORM_INFRA_DIR}/cf-domain.txt" 2>/dev/null | tr -d '[:space:]') || CF_DOMAIN=""
  [ "$CF_DOMAIN" = "None" ] && CF_DOMAIN=""

  if [ -z "$CF_DOMAIN" ] && [ -n "$VPC_ORIGIN_ID" ]; then
    # Fallback: CF not created in background — create now (VPC Origin is Deployed)
    echo "  ▸ CloudFront not created in background — retrying now..."
    ALB_DNS=$(aws elbv2 describe-load-balancers \
      --load-balancer-arns "$ALB_ARN" --region "$REGION" \
      --query 'LoadBalancers[0].DNSName' --output text 2>/dev/null)
    HUB_CLUSTER_NAME="${RESOURCE_PREFIX}-hub"
    CF_DOMAIN=$(aws cloudfront create-distribution \
      --distribution-config "{
        \"CallerReference\": \"${HUB_CLUSTER_NAME}-platform-$(date +%s)\",
        \"Comment\": \"${HUB_CLUSTER_NAME}-platform\",
        \"Enabled\": true,
        \"Origins\": {\"Quantity\": 1, \"Items\": [{
          \"Id\": \"vpc-origin\",
          \"DomainName\": \"$ALB_DNS\",
          \"VpcOriginConfig\": {
            \"VpcOriginId\": \"$VPC_ORIGIN_ID\",
            \"OriginReadTimeout\": 60,
            \"OriginKeepaliveTimeout\": 5
          }
        }]},
        \"DefaultCacheBehavior\": {
          \"TargetOriginId\": \"vpc-origin\",
          \"ViewerProtocolPolicy\": \"redirect-to-https\",
          \"AllowedMethods\": {\"Quantity\": 7,
            \"Items\": [\"GET\",\"HEAD\",\"OPTIONS\",\"PUT\",\"POST\",\"PATCH\",\"DELETE\"],
            \"CachedMethods\": {\"Quantity\": 2, \"Items\": [\"GET\",\"HEAD\"]}},
          \"CachePolicyId\": \"4135ea2d-6df8-44a3-9df3-4b5a84be39ad\",
          \"OriginRequestPolicyId\": \"216adef6-5c7f-47e4-b989-5492eafa07d3\",
          \"Compress\": true},
        \"ViewerCertificate\": {\"CloudFrontDefaultCertificate\": true},
        \"PriceClass\": \"PriceClass_100\"
      }" --query "Distribution.DomainName" --output text 2>/dev/null) || CF_DOMAIN=""
  fi

  if [ -n "$CF_DOMAIN" ] && [ "$CF_DOMAIN" != "None" ]; then
    yq -i ".domain = \"$CF_DOMAIN\"" "$OUTPUT_FILE" 2>/dev/null || \
      sed -i "s|domain: .*|domain: \"$CF_DOMAIN\"|" "$OUTPUT_FILE"
    mkdir -p "$(dirname "$OUTPUT_FILE")/../private"
    echo -n "$CF_DOMAIN" > "$(dirname "$OUTPUT_FILE")/../private/cloudfront-domain"
    echo "  ✓ CloudFront: $CF_DOMAIN"
    echo "  ✓ domain written to config: $CF_DOMAIN"
  fi
  rm -rf "$_PLATFORM_INFRA_DIR" 2>/dev/null || true
fi

# --- Validate --------------------------------------------------------------
echo "▸ Validating generated YAML..."
yq '.' "$OUTPUT_FILE" >/dev/null

echo "✓ config.local.yaml created:"
echo "    clusterProvider=$CLUSTER_PROVIDER region=$REGION accountId=$ACCOUNT_ID prefix=$RESOURCE_PREFIX"
echo "    clusterName=${RESOURCE_PREFIX}-hub adminRole=$ADMIN_ROLE_NAME"
echo "    idcInstance=$IDC_ARN adminGroupId=${IDC_GROUP:-<empty>}"
echo "    domain=\"\" (CloudFront exposure mode) cloudfrontDomain=${CF_DOMAIN:-<not detected>}"
