#!/usr/bin/env bash
# Reserve a CloudFront hostname BEFORE the platform is installed.
#
# Creates a CloudFront distribution pointed at a deliberately unresolvable placeholder
# origin and prints its *.cloudfront.net hostname. create-distribution returns DomainName
# immediately, so this takes about a second and needs no VPC, no load balancer, and no
# waiting.
#
# Why this exists: the platform needs its ingress hostname at install time (Keycloak realm
# URLs, the OIDC issuer, ingress hosts, the ArgoCD and Backstage base URLs). Deriving that
# hostname from infrastructure the install itself creates is circular. Reserving the name
# up front breaks the circle, so `domain` is an ordinary static config value and the
# platform needs no asynchronous domain machinery at all.
#
# Consumer flow:
#   1. domain=$(scripts/cloudfront-reserve-domain.sh)   # this script, seconds
#   2. write domain + insecure: true into config.local.yaml, then `task install`
#   3. scripts/cloudfront-attach-origin.sh              # after install, points CF at the ALB
#
# Until step 3 the distribution serves errors, which is expected and harmless: nothing
# resolves that hostname until the platform is up.
#
# Idempotent: re-running returns the existing distribution's hostname and creates nothing,
# so it is safe in a re-provisioning loop.
#
# Inputs (env, falling back to PLATFORM_CONFIG_FILE):
#   PLATFORM_CONFIG_FILE  path to config.local.yaml   (default: ./config.local.yaml)
#   HUB_CLUSTER_NAME      cluster name                (default: .hub.clusterName)
#   CF_COMMENT            distribution Comment, the identity used to find it later
#                                                     (default: <HUB_CLUSTER_NAME>-platform)
#   CF_PRICE_CLASS        PriceClass_100|200|All      (default: PriceClass_100)
#
# Output: the hostname as the LAST line of stdout; progress on stderr.
# Exit:   0 ok · 1 bad prerequisite
set -uo pipefail

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$1" >&2; }
die() { printf '[%s] ERROR: %s\n' "$(date +%H:%M:%S)" "$1" >&2; exit 1; }

CONFIG_FILE="${PLATFORM_CONFIG_FILE:-./config.local.yaml}"
cfg() {
  [ -f "$CONFIG_FILE" ] || { echo ""; return 0; }
  command -v yq >/dev/null 2>&1 || { echo ""; return 0; }
  yq -r "$1 // \"\"" "$CONFIG_FILE" 2>/dev/null | grep -v '^null$' || echo ""
}

HUB_CLUSTER_NAME="${HUB_CLUSTER_NAME:-$(cfg '.hub.clusterName')}"
[ -n "$HUB_CLUSTER_NAME" ] || die "cluster name unknown (set HUB_CLUSTER_NAME, or .hub.clusterName in $CONFIG_FILE)"
CF_COMMENT="${CF_COMMENT:-${HUB_CLUSTER_NAME}-platform}"
PRICE_CLASS="${CF_PRICE_CLASS:-PriceClass_100}"

command -v aws >/dev/null 2>&1 || die "aws CLI not found"

# The Comment is the distribution's durable identity: cloudfront-attach-origin.sh finds it
# the same way. Keep the two in step if you override it.
EXISTING=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Comment=='$CF_COMMENT'].DomainName | [0]" \
  --output text 2>/dev/null | tr -d '[:space:]')
[ "$EXISTING" = "None" ] && EXISTING=""
if [ -n "$EXISTING" ]; then
  log "reusing existing distribution for '$CF_COMMENT'"
  printf '%s\n' "$EXISTING"
  exit 0
fi

# placeholder.invalid can never resolve (.invalid is reserved by RFC 2606). CloudFront
# accepts it: an origin is not validated at creation time. Using an unresolvable name
# rather than a real one makes it obvious in logs that no origin is attached yet.
log "creating distribution for '$CF_COMMENT' (placeholder origin, no infrastructure needed)"
OUT=$(aws cloudfront create-distribution --distribution-config "{
    \"CallerReference\": \"${CF_COMMENT}-$(date +%s)\",
    \"Comment\": \"$CF_COMMENT\",
    \"Enabled\": true,
    \"Origins\": {\"Quantity\": 1, \"Items\": [{
      \"Id\": \"platform-origin\",
      \"DomainName\": \"placeholder.invalid\",
      \"CustomOriginConfig\": {
        \"HTTPPort\": 80,
        \"HTTPSPort\": 443,
        \"OriginProtocolPolicy\": \"http-only\",
        \"OriginSslProtocols\": {\"Quantity\": 1, \"Items\": [\"TLSv1.2\"]},
        \"OriginReadTimeout\": 60,
        \"OriginKeepaliveTimeout\": 5
      }
    }]},
    \"DefaultCacheBehavior\": {
      \"TargetOriginId\": \"platform-origin\",
      \"ViewerProtocolPolicy\": \"redirect-to-https\",
      \"AllowedMethods\": {\"Quantity\": 7,
        \"Items\": [\"GET\",\"HEAD\",\"OPTIONS\",\"PUT\",\"POST\",\"PATCH\",\"DELETE\"],
        \"CachedMethods\": {\"Quantity\": 2, \"Items\": [\"GET\",\"HEAD\"]}},
      \"CachePolicyId\": \"4135ea2d-6df8-44a3-9df3-4b5a84be39ad\",
      \"OriginRequestPolicyId\": \"216adef6-5c7f-47e4-b989-5492eafa07d3\",
      \"Compress\": true},
    \"ViewerCertificate\": {\"CloudFrontDefaultCertificate\": true},
    \"PriceClass\": \"$PRICE_CLASS\"
  }" --output json 2>&1)
# shellcheck disable=SC2181
if [ $? -ne 0 ]; then
  printf '%s\n' "$OUT" | head -5 >&2
  die "create-distribution failed"
fi

CF_DOMAIN=$(printf '%s' "$OUT" | jq -r '.Distribution.DomainName // empty' 2>/dev/null)
DIST_ID=$(printf '%s' "$OUT" | jq -r '.Distribution.Id // empty' 2>/dev/null)
[ -n "$CF_DOMAIN" ] || die "distribution created but no DomainName returned"

log "reserved $CF_DOMAIN (id $DIST_ID)"
log "next: set domain + insecure:true in config, install, then run cloudfront-attach-origin.sh"
printf '%s\n' "$CF_DOMAIN"
