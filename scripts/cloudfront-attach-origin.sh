#!/usr/bin/env bash
# Point a reserved CloudFront distribution at the platform's load balancer, AFTER install.
#
# Run this once `task install` has finished and the AWS Load Balancer Controller has created
# the platform ALB. It swaps the distribution's placeholder origin for a CloudFront VPC
# origin bound to that ALB, so traffic reaches the platform over a private path inside the
# VPC instead of across the internet.
#
# Pairs with scripts/cloudfront-reserve-domain.sh (run before install). Together they let
# the hostname be known up front while the load balancer is still created normally by the
# platform, so no VPC or ALB has to be provisioned in advance.
#
# Also self-heals the documented curl-000 failure: if the ALB was replaced (its scheme is
# immutable, so a mismatch makes the controller delete and recreate it) the VPC origin is
# left bound to a load balancer that no longer exists and every platform URL hangs. Because
# a VPC origin cannot be re-pointed while attached to a distribution, recovery is
# create-new / swap / delete-old, which is what this script does when it sees drift.
#
# Idempotent: exits 0 having changed nothing when the distribution already points at the
# current ALB, so it is safe to re-run or to call on every deploy.
#
# Requires: the ALB to exist. It is named <clusterName>-platform because the platform sets
# IngressClassParams.loadBalancerName when insecure is true (gitops/addons/registry/core.yaml).
#
# Inputs (env, falling back to PLATFORM_CONFIG_FILE):
#   PLATFORM_CONFIG_FILE  path to config.local.yaml    (default: ./config.local.yaml)
#   HUB_CLUSTER_NAME      cluster name                 (default: .hub.clusterName)
#   AWS_REGION            region                       (default: .aws.region)
#   CF_COMMENT            distribution Comment         (default: <HUB_CLUSTER_NAME>-platform)
#   ALB_NAME              override the ALB name        (default: <HUB_CLUSTER_NAME>-platform)
#   CF_TIMEOUT_SECONDS    VPC origin deploy budget     (default: 1200; measured ~540s)
#
# Exit: 0 ok or already correct · 1 bad prerequisite · 2 VPC origin never deployed
set -uo pipefail

log()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$1" >&2; }
die()  { printf '[%s] ERROR: %s\n' "$(date +%H:%M:%S)" "$1" >&2; exit "${2:-1}"; }

CONFIG_FILE="${PLATFORM_CONFIG_FILE:-./config.local.yaml}"
cfg() {
  [ -f "$CONFIG_FILE" ] || { echo ""; return 0; }
  command -v yq >/dev/null 2>&1 || { echo ""; return 0; }
  yq -r "$1 // \"\"" "$CONFIG_FILE" 2>/dev/null | grep -v '^null$' || echo ""
}

HUB_CLUSTER_NAME="${HUB_CLUSTER_NAME:-$(cfg '.hub.clusterName')}"
REGION="${AWS_REGION:-$(cfg '.aws.region')}"
[ -n "$HUB_CLUSTER_NAME" ] || die "cluster name unknown (set HUB_CLUSTER_NAME, or .hub.clusterName in $CONFIG_FILE)"
[ -n "$REGION" ]          || die "region unknown (set AWS_REGION, or .aws.region in $CONFIG_FILE)"

CF_COMMENT="${CF_COMMENT:-${HUB_CLUSTER_NAME}-platform}"
ALB_NAME="${ALB_NAME:-${HUB_CLUSTER_NAME}-platform}"
VPC_ORIGIN_NAME="${HUB_CLUSTER_NAME}-platform-vpc-origin"
TIMEOUT="${CF_TIMEOUT_SECONDS:-1200}"

command -v aws >/dev/null 2>&1 || die "aws CLI not found"
command -v jq  >/dev/null 2>&1 || die "jq not found"

# ── 1. the ALB the platform created ─────────────────────────────────────────────────────
ALB=$(aws elbv2 describe-load-balancers --names "$ALB_NAME" --region "$REGION" \
  --query 'LoadBalancers[0].[LoadBalancerArn,DNSName,Scheme,State.Code]' --output text 2>/dev/null)
case "$ALB" in ''|*None*)
  die "load balancer '$ALB_NAME' not found in $REGION.
     Run this AFTER 'task install' has finished and the platform ingresses have an address.
     Check:  kubectl get ingress -A" ;;
esac
ALB_ARN=$(printf '%s' "$ALB" | awk '{print $1}')
ALB_DNS=$(printf '%s' "$ALB" | awk '{print $2}')
ALB_SCHEME=$(printf '%s' "$ALB" | awk '{print $3}')
ALB_STATE=$(printf '%s' "$ALB" | awk '{print $4}')
log "ALB $ALB_NAME ($ALB_SCHEME, $ALB_STATE)"
[ "$ALB_STATE" = "active" ] || log "WARNING: ALB state is '$ALB_STATE', not 'active' — continuing"

# ── 2. the reserved distribution ────────────────────────────────────────────────────────
DIST_ID=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Comment=='$CF_COMMENT'].Id | [0]" --output text 2>/dev/null | tr -d '[:space:]')
[ "$DIST_ID" = "None" ] && DIST_ID=""
[ -n "$DIST_ID" ] || die "no distribution with Comment '$CF_COMMENT'.
     Run scripts/cloudfront-reserve-domain.sh first (before installing)."
log "distribution $DIST_ID"

# ── 3. already correct? then do nothing ─────────────────────────────────────────────────
CUR_VO=$(aws cloudfront get-distribution --id "$DIST_ID" \
  --query 'Distribution.DistributionConfig.Origins.Items[0].VpcOriginConfig.VpcOriginId' \
  --output text 2>/dev/null | tr -d '[:space:]')
[ "$CUR_VO" = "None" ] && CUR_VO=""
if [ -n "$CUR_VO" ]; then
  CUR_ARN=$(aws cloudfront get-vpc-origin --id "$CUR_VO" \
    --query 'VpcOrigin.VpcOriginEndpointConfig.Arn' --output text 2>/dev/null | tr -d '[:space:]')
  if [ "$CUR_ARN" = "$ALB_ARN" ]; then
    log "already pointed at the current ALB via $CUR_VO — nothing to do"
    exit 0
  fi
  log "DRIFT: VPC origin $CUR_VO points at a different ALB"
  log "  bound to: $CUR_ARN"
  log "  current:  $ALB_ARN"
  log "  this is the stale-origin failure (all platform URLs hang). Re-pointing."
fi

# ── 4. create or reuse a VPC origin for this ALB ────────────────────────────────────────
# A VPC origin cannot be edited while attached to a distribution, so on drift we make a new
# one rather than trying to update the existing one in place.
VO_ID=""
for id in $(aws cloudfront list-vpc-origins --query 'VpcOriginList.Items[].Id' --output text 2>/dev/null); do
  arn=$(aws cloudfront get-vpc-origin --id "$id" \
    --query 'VpcOrigin.VpcOriginEndpointConfig.Arn' --output text 2>/dev/null | tr -d '[:space:]')
  if [ "$arn" = "$ALB_ARN" ]; then VO_ID="$id"; log "reusing VPC origin $id (already bound to this ALB)"; break; fi
done

if [ -z "$VO_ID" ]; then
  # Name must be unique per origin, so on drift suffix it rather than colliding with the old.
  NAME="$VPC_ORIGIN_NAME"
  if aws cloudfront list-vpc-origins --query "VpcOriginList.Items[?Name=='$NAME'].Id" \
       --output text 2>/dev/null | grep -q .; then NAME="${NAME}-$(date +%s)"; fi
  log "creating VPC origin '$NAME' for the current ALB"
  VO_ID=$(aws cloudfront create-vpc-origin --vpc-origin-endpoint-config "{
      \"Name\": \"$NAME\",
      \"Arn\": \"$ALB_ARN\",
      \"HTTPPort\": 80,
      \"HTTPSPort\": 443,
      \"OriginProtocolPolicy\": \"http-only\",
      \"OriginSslProtocols\": {\"Quantity\": 1, \"Items\": [\"TLSv1.2\"]}
    }" --query 'VpcOrigin.Id' --output text 2>&1)
  # Ids look like vo_Ie0pJyppijUFcTt0nZRuPJ — an UNDERSCORE, not a hyphen. Validate by shape,
  # not by prefix: a prefix guess here previously misread a success as a failure.
  printf '%s' "$VO_ID" | grep -qE '^[A-Za-z0-9_-]{8,}$' || die "create-vpc-origin failed: $VO_ID"
  log "created $VO_ID"
fi

# ── 5. wait for Deployed (a distribution can only attach a Deployed VPC origin) ─────────
STATE=$(aws cloudfront get-vpc-origin --id "$VO_ID" --query 'VpcOrigin.Status' --output text 2>/dev/null || echo Unknown)
if [ "$STATE" != "Deployed" ]; then
  log "waiting for VPC origin to deploy (budget ${TIMEOUT}s; typically ~9 min)"
  ELAPSED=0
  while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
    STATE=$(aws cloudfront get-vpc-origin --id "$VO_ID" --query 'VpcOrigin.Status' --output text 2>/dev/null || echo Unknown)
    [ "$STATE" = "Deployed" ] && break
    [ "$STATE" = "Failed" ] && die "VPC origin $VO_ID entered Failed state"
    [ $((ELAPSED % 120)) -eq 0 ] && [ "$ELAPSED" -gt 0 ] && log "  ${ELAPSED}s: $STATE"
    sleep 15; ELAPSED=$((ELAPSED + 15))
  done
  [ "$STATE" = "Deployed" ] || die "VPC origin $VO_ID still '$STATE' after ${TIMEOUT}s" 2
fi
log "VPC origin Deployed"

# ── 6. swap the distribution's origin ───────────────────────────────────────────────────
aws cloudfront get-distribution-config --id "$DIST_ID" --output json > /tmp/cf-attach-$$.json \
  || die "could not read distribution config"
ETAG=$(jq -r '.ETag' /tmp/cf-attach-$$.json)
jq --arg dns "$ALB_DNS" --arg vo "$VO_ID" '
  .DistributionConfig
  | .Origins.Items[0] |= (
      del(.CustomOriginConfig)
      | .DomainName = $dns
      | .VpcOriginConfig = {"VpcOriginId": $vo, "OriginReadTimeout": 60, "OriginKeepaliveTimeout": 5}
    )' /tmp/cf-attach-$$.json > /tmp/cf-attach-new-$$.json

RES=$(aws cloudfront update-distribution --id "$DIST_ID" --if-match "$ETAG" \
  --distribution-config "file:///tmp/cf-attach-new-$$.json" --output json 2>&1)
# shellcheck disable=SC2181
if [ $? -ne 0 ]; then
  printf '%s\n' "$RES" | head -8 >&2
  rm -f /tmp/cf-attach-$$.json /tmp/cf-attach-new-$$.json
  die "update-distribution failed"
fi
rm -f /tmp/cf-attach-$$.json /tmp/cf-attach-new-$$.json

CF_DOMAIN=$(printf '%s' "$RES" | jq -r '.Distribution.DomainName')
log "attached: $CF_DOMAIN -> $ALB_DNS (via $VO_ID)"

# ── 7. retire the superseded VPC origin, if any ─────────────────────────────────────────
if [ -n "${CUR_VO:-}" ] && [ "$CUR_VO" != "$VO_ID" ]; then
  log "old VPC origin $CUR_VO is now detached; it can be deleted once the distribution"
  log "  finishes deploying:  aws cloudfront delete-vpc-origin --id $CUR_VO --if-match <etag>"
fi

log "CloudFront propagation takes a few minutes; until then expect intermittent errors."
printf '%s\n' "$CF_DOMAIN"
