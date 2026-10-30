#!/usr/bin/env bash
# Print the EKS cluster name of this stack's dev|prod spoke. Read-only.
#
# Usage: resolve-spoke-cluster.sh PREFIX REGION ENV [PRESET_NAME]
#   ENV          dev | prod
#   PRESET_NAME  optional value already stored in <hub>/config (spoke_<env>_cluster_name);
#                an operator-set name always wins, as long as that cluster exists.
#
# Why: the workshop names its spokes <prefix>-spoke-dev / <prefix>-spoke-prod, but outside
# the workshop a spoke is named by whoever declares it (e.g. <prefix>-dev). A name built
# from the prefix therefore misses those spokes. Every kro-provisioned spoke EKS cluster
# carries the tags platform.gitops.io/prefix=<prefix> and environment=<dev|prod>
# (rg-eks.yaml), so the spoke is discovered by those tags.
#
# Resolution order (first hit wins):
#   1. PRESET_NAME, if that cluster exists
#   2. <prefix>-spoke-<env>, if it exists          (workshop: unchanged, one API call)
#   3. the cluster tagged prefix=<prefix> + environment=<env> (ACTIVE matches preferred over
#      any other status; first by name among the preferred set; WARN on stderr when several
#      match)
# Nothing found, or any EKS API error: print nothing and exit 0 (caller skips the spoke).
# Only the cluster name goes to stdout.
set -u
PREFIX="${1:?prefix}"; REGION="${2:?region}"; ENV_NAME="${3:?env (dev|prod)}"; PRESET="${4:-}"

exists() {
  local out rc
  out=$(aws eks describe-cluster --name "$1" --region "$REGION" --query 'cluster.status' --output text 2>&1)
  rc=$?
  if [ $rc -ne 0 ]; then
    case "$out" in
      *ResourceNotFoundException*) return 1 ;;  # genuinely absent: caller may fall through
      *)
        # A throttled or denied call is not "absent" -- per the header contract, any other
        # EKS API error means print nothing and let the caller skip the spoke, instead of
        # treating it as missing and risking a tag-scan match on a different cluster.
        echo "WARN: describe-cluster $1 failed, not ResourceNotFoundException ($(printf '%s' "$out" | head -1)); skipping spoke." >&2
        exit 0 ;;
    esac
  fi
  [ -n "$out" ] && [ "$out" != "None" ]
}

if [ -n "$PRESET" ] && exists "$PRESET"; then echo "$PRESET"; exit 0; fi
CONV="${PREFIX}-spoke-${ENV_NAME}"
if exists "$CONV"; then echo "$CONV"; exit 0; fi

FOUND=""
ACTIVE_FOUND=""
for C in $(aws eks list-clusters --region "$REGION" --query 'clusters[]' --output text 2>/dev/null | tr '\t' '\n' | sort); do
  [ -n "$C" ] || continue
  # "<prefix><TAB><environment><TAB><status>"; a missing tag prints "None".
  T=$(aws eks describe-cluster --name "$C" --region "$REGION" \
        --query 'cluster.[tags."platform.gitops.io/prefix", tags.environment, status]' --output text 2>/dev/null) || continue
  IFS="$(printf '\t')" read -r TP TE TS <<EOF
$T
EOF
  if [ "$TP" = "$PREFIX" ] && [ "$TE" = "$ENV_NAME" ]; then
    FOUND="$FOUND $C"
    [ "$TS" = "ACTIVE" ] && ACTIVE_FOUND="$ACTIVE_FOUND $C"
  fi
done
# A cluster being deleted (or otherwise non-ACTIVE) must not win over one that is ACTIVE just
# because it sorts first; fall back to any match only when none is ACTIVE.
if [ -n "$ACTIVE_FOUND" ]; then SELECTED="$ACTIVE_FOUND"; else SELECTED="$FOUND"; fi
set -- $SELECTED
if [ $# -gt 1 ]; then
  echo "WARN: $# clusters are tagged prefix=$PREFIX environment=$ENV_NAME ($*); using $1. Set spoke_${ENV_NAME}_cluster_name in the hub config to choose." >&2
fi
[ $# -ge 1 ] && echo "$1"
exit 0
