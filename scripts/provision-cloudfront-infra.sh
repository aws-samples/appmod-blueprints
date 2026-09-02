#!/usr/bin/env bash
# Provision the CloudFront infrastructure a platform install needs in front of it.
#
# Creates, idempotently, in this order:
#   1. a security group for the platform ALB (ingress :80 from the VPC CIDR)
#   2. an INTERNAL Application Load Balancer named "<clusterName>-platform", tagged so the
#      AWS Load Balancer Controller ADOPTS it instead of creating a second one
#   3. an HTTP:80 listener with a 404 fixed-response default (the LBC adds the real rules)
#   4. a CloudFront VPC origin pointing at that ALB
#   5. a CloudFront distribution with Comment "<clusterName>-platform"
#
# Run this BEFORE `task install`. The ALB must exist first so the LBC adopts it; if the LBC
# creates its own, CloudFront ends up pointed at an ALB that is later replaced and every
# platform URL hangs (curl 000). See docs/platform/domain-resolution-design.md and the
# "CloudFront platform URLs hang" runbook in .kiro/steering/troubleshooting.md.
#
# The VPC and its subnets are NOT created here — supply an existing VPC. Subnets must be
# private and in at least 2 availability zones. This script tags them
# kubernetes.io/role/internal-elb=1 so the LBC discovers the same subnet set.
#
# Inputs (env; falls back to PLATFORM_CONFIG_FILE, which OAP/the workshop has already written):
#   PLATFORM_CONFIG_FILE  path to config.local.yaml            (default: ./config.local.yaml)
#   HUB_CLUSTER_NAME      cluster name                         (default: .hub.clusterName)
#   VPC_ID                existing VPC id                      (default: .hub.network.vpcId)
#   SUBNET_IDS            space/comma-separated private subnets (default: .hub.network.subnetIds,
#                         else discovered by the internal-elb tag)
#   AWS_REGION            region                               (default: .aws.region)
#   SKIP_DISTRIBUTION     "true" to stop after the VPC origin
#
# Output: the CloudFront domain name as the LAST line of stdout. Progress goes to stderr,
# so `DOMAIN=$(provision-cloudfront-infra.sh)` yields just the hostname.
#
# Exit: 0 ok · 1 bad prerequisite · 2 timed out waiting for the VPC origin
#
# Pair with scripts/resolve-cloudfront-domain.sh, which finds the distribution created here
# by its Comment. Using both means the hostname never has to be passed between steps.
set -euo pipefail

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$1" >&2; }
die() { printf '[%s] ERROR: %s\n' "$(date +%H:%M:%S)" "$1" >&2; exit "${2:-1}"; }

CONFIG_FILE="${PLATFORM_CONFIG_FILE:-./config.local.yaml}"
cfg() {  # cfg <yq-path> — empty string when absent, never the literal "null"
  [ -f "$CONFIG_FILE" ] || { echo ""; return 0; }
  command -v yq >/dev/null 2>&1 || { echo ""; return 0; }
  yq -r "$1 // \"\"" "$CONFIG_FILE" 2>/dev/null | grep -v '^null$' || echo ""
}

HUB_CLUSTER_NAME="${HUB_CLUSTER_NAME:-$(cfg '.hub.clusterName')}"
VPC_ID="${VPC_ID:-$(cfg '.hub.network.vpcId')}"
REGION="${AWS_REGION:-$(cfg '.aws.region')}"
SUBNET_IDS="${SUBNET_IDS:-$(cfg '.hub.network.subnetIds | join(" ")')}"

[ -n "$HUB_CLUSTER_NAME" ] || die "cluster name unknown (set HUB_CLUSTER_NAME or .hub.clusterName in $CONFIG_FILE)"
[ -n "$VPC_ID" ]          || die "VPC id unknown (set VPC_ID or .hub.network.vpcId in $CONFIG_FILE). This script does not create a VPC."
[ -n "$REGION" ]          || die "region unknown (set AWS_REGION or .aws.region in $CONFIG_FILE)"

ALB_NAME="${HUB_CLUSTER_NAME}-platform"
SG_NAME="${HUB_CLUSTER_NAME}-platform-alb-sg"
VPC_ORIGIN_NAME="${HUB_CLUSTER_NAME}-platform-vpc-origin"
CF_COMMENT="${HUB_CLUSTER_NAME}-platform"

log "cluster=$HUB_CLUSTER_NAME vpc=$VPC_ID region=$REGION"

# ── 0. VPC must resolve: the SG, ALB and VPC origin are all created inside it ────────────
VPC_CIDR=$(aws ec2 describe-vpcs --vpc-ids "$VPC_ID" --region "$REGION" \
  --query 'Vpcs[0].CidrBlock' --output text 2>/dev/null || echo "")
[ -n "$VPC_CIDR" ] && [ "$VPC_CIDR" != "None" ] || die "VPC $VPC_ID not found in $REGION"
log "VPC CIDR: $VPC_CIDR"

# ── 1. ALB security group ───────────────────────────────────────────────────────────────
SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
  --region "$REGION" --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "")
[ "$SG_ID" = "None" ] && SG_ID=""
if [ -z "$SG_ID" ]; then
  SG_ID=$(aws ec2 create-security-group --group-name "$SG_NAME" \
    --description "Platform ALB (internal, CloudFront VPC Origin)" \
    --vpc-id "$VPC_ID" --region "$REGION" --query 'GroupId' --output text)
  # CloudFront VPC-origin traffic originates inside the VPC, so the CIDR covers it.
  aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
    --protocol tcp --port 80 --cidr "$VPC_CIDR" --region "$REGION" >/dev/null 2>&1 || true
  log "created SG $SG_ID"
else
  log "reusing SG $SG_ID"
fi

# ── 2. Private subnets, one per AZ, tagged for LBC discovery ─────────────────────────────
SUBNETS=$(printf '%s' "${SUBNET_IDS:-}" | tr -d "[]'\"" | tr ',' ' ')
if [ -z "${SUBNETS// /}" ]; then
  log "no subnets supplied — discovering by kubernetes.io/role/internal-elb=1"
  SUBNETS=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:kubernetes.io/role/internal-elb,Values=1" \
    --region "$REGION" --query 'Subnets[].[SubnetId,AvailabilityZone]' --output text 2>/dev/null |
    sort -k2 -u | awk '{print $1}' | tr '\n' ' ')
fi
[ -n "${SUBNETS// /}" ] || die "no private subnets found in $VPC_ID. Supply SUBNET_IDS or tag them kubernetes.io/role/internal-elb=1"

AZ_COUNT=$(aws ec2 describe-subnets --subnet-ids $SUBNETS --region "$REGION" \
  --query 'Subnets[].AvailabilityZone' --output text 2>/dev/null | tr '\t' '\n' | sort -u | wc -l | tr -d ' ')
[ "$AZ_COUNT" -ge 2 ] || die "an ALB needs subnets in >=2 AZs; got $AZ_COUNT for: $SUBNETS"

for sn in $SUBNETS; do
  aws ec2 create-tags --resources "$sn" --region "$REGION" \
    --tags Key=kubernetes.io/role/internal-elb,Value=1 >/dev/null 2>&1 || true
done
log "subnets ($AZ_COUNT AZs): $SUBNETS"

# ── 3. Internal ALB, tagged so the LBC adopts rather than recreates ──────────────────────
ALB_ARN=$(aws elbv2 describe-load-balancers --names "$ALB_NAME" --region "$REGION" \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || echo "")
[ "$ALB_ARN" = "None" ] && ALB_ARN=""
if [ -z "$ALB_ARN" ]; then
  ALB_ARN=$(aws elbv2 create-load-balancer --name "$ALB_NAME" --subnets $SUBNETS \
    --security-groups "$SG_ID" --scheme internal --type application \
    --tags Key=elbv2.k8s.aws/cluster,Value="$HUB_CLUSTER_NAME" \
           Key=ingress.k8s.aws/stack,Value=platform \
           Key=ingress.k8s.aws/resource,Value=LoadBalancer \
    --region "$REGION" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || echo "")
  [ "$ALB_ARN" = "None" ] && ALB_ARN=""
  [ -n "$ALB_ARN" ] || die "ALB creation failed for $ALB_NAME"
  # Default 404; the LBC replaces the rules when it adopts the ALB.
  aws elbv2 create-listener --load-balancer-arn "$ALB_ARN" --protocol HTTP --port 80 \
    --default-actions "Type=fixed-response,FixedResponseConfig={MessageBody=Not Found,StatusCode=404,ContentType=text/plain}" \
    --region "$REGION" >/dev/null 2>&1 || true
  log "created internal ALB $ALB_NAME"
else
  SCHEME=$(aws elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" --region "$REGION" \
    --query 'LoadBalancers[0].Scheme' --output text 2>/dev/null || echo "")
  # Scheme is immutable: if it is internet-facing the LBC will delete and recreate the ALB,
  # orphaning the VPC origin and hanging every platform URL.
  [ "$SCHEME" = "internal" ] || die "existing ALB $ALB_NAME has scheme '$SCHEME'; CloudFront VPC origins require 'internal'. Delete it and re-run."
  log "reusing internal ALB $ALB_NAME"
fi

ALB_DNS=$(aws elbv2 describe-load-balancers --load-balancer-arns "$ALB_ARN" --region "$REGION" \
  --query 'LoadBalancers[0].DNSName' --output text)

# ── 4. CloudFront VPC origin ────────────────────────────────────────────────────────────
VPC_ORIGIN_ID=$(aws cloudfront list-vpc-origins \
  --query "VpcOriginList.Items[?Name=='$VPC_ORIGIN_NAME'].Id" --output text 2>/dev/null | tr -d '[:space:]' || echo "")
[ "$VPC_ORIGIN_ID" = "None" ] && VPC_ORIGIN_ID=""
if [ -z "$VPC_ORIGIN_ID" ]; then
  VPC_ORIGIN_ID=$(aws cloudfront create-vpc-origin --vpc-origin-endpoint-config "{
      \"Name\": \"$VPC_ORIGIN_NAME\",
      \"Arn\": \"$ALB_ARN\",
      \"HTTPPort\": 80,
      \"HTTPSPort\": 443,
      \"OriginProtocolPolicy\": \"http-only\",
      \"OriginSslProtocols\": {\"Quantity\": 1, \"Items\": [\"TLSv1.2\"]}
    }" --query 'VpcOrigin.Id' --output text)
  log "created VPC origin $VPC_ORIGIN_ID"
else
  ORIGIN_ARN=$(aws cloudfront get-vpc-origin --id "$VPC_ORIGIN_ID" \
    --query 'VpcOrigin.VpcOriginEndpointConfig.Arn' --output text 2>/dev/null || echo "")
  if [ -n "$ORIGIN_ARN" ] && [ "$ORIGIN_ARN" != "$ALB_ARN" ]; then
    # A VPC origin cannot be re-pointed while attached to a distribution.
    die "VPC origin $VPC_ORIGIN_ID points at a different ALB:
       origin: $ORIGIN_ARN
       actual: $ALB_ARN
     This is the stale-VPC-origin failure (all platform URLs hang, curl 000). Recovery is
     create-new / swap / delete-old — see .kiro/steering/troubleshooting.md."
  fi
  log "reusing VPC origin $VPC_ORIGIN_ID"
fi

if [ "${SKIP_DISTRIBUTION:-}" = "true" ]; then
  log "SKIP_DISTRIBUTION=true — stopping after the VPC origin"
  exit 0
fi

# ── 5. Distribution (reuse if one already carries our Comment) ───────────────────────────
CF_DOMAIN=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Comment=='$CF_COMMENT'].DomainName | [0]" \
  --output text 2>/dev/null | tr -d '[:space:]' || echo "")
[ "$CF_DOMAIN" = "None" ] && CF_DOMAIN=""

if [ -z "$CF_DOMAIN" ]; then
  # A distribution can only attach a Deployed VPC origin, so this wait is unavoidable here.
  log "waiting for VPC origin to reach Deployed (up to 15 min)..."
  STATE=""
  for i in $(seq 1 60); do
    STATE=$(aws cloudfront get-vpc-origin --id "$VPC_ORIGIN_ID" \
      --query 'VpcOrigin.Status' --output text 2>/dev/null || echo "Pending")
    [ "$STATE" = "Deployed" ] && break
    [ $((i % 4)) -eq 0 ] && log "  VPC origin after $((i * 15))s: $STATE"
    sleep 15
  done
  [ "$STATE" = "Deployed" ] || die "VPC origin $VPC_ORIGIN_ID still '$STATE' after 15 min" 2
  log "VPC origin Deployed"

  log "creating CloudFront distribution..."
  CF_DOMAIN=$(aws cloudfront create-distribution --distribution-config "{
      \"CallerReference\": \"${HUB_CLUSTER_NAME}-platform-$(date +%s)\",
      \"Comment\": \"$CF_COMMENT\",
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
    }" --query 'Distribution.DomainName' --output text)
  [ -n "$CF_DOMAIN" ] && [ "$CF_DOMAIN" != "None" ] || die "distribution creation failed"
  log "created distribution: $CF_DOMAIN"
else
  log "reusing distribution: $CF_DOMAIN"
fi

log "done — set insecure: true and domainResolver: scripts/resolve-cloudfront-domain.sh"
printf '%s\n' "$CF_DOMAIN"
