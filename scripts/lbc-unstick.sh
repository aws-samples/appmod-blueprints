#!/usr/bin/env bash
# One evaluation of "the platform ALB is late: is the load balancer controller (LBC) stuck?".
#
# Called by the ALB wait loop of scripts/cloudfront-attach-origin.sh (about once a minute).
# It does nothing until the ALB has been missing for LBC_UNSTICK_AFTER seconds, so a healthy
# install (ALB at +6 to +8 min after install:hub) never reaches it.
#
# Why not an Argo CD retry kick: the LBC app already caps its retry backoff at 1m
# (gitops/addons/registry/core.yaml), so a kick bypasses a timer it does not wait on. The
# observed stall is different: a 429 from the EKS control plane on the first apply of one
# object (the ServiceAccount) leaves the Deployment without pods, and Argo CD does not
# re-apply for ~12 min. This helper reads the hub, names the symptom, and acts on it.
#
# Diagnostics, read-only, in this order:
#   missing   ServiceAccount or Deployment absent             -> A: argocd-app-kick.sh <lbc app>
#   rsfailed  Deployment has no available pod AND its newest
#             ReplicaSet reports ReplicaFailure                -> B: rollout restart the Deployment
#   noaddr    Deployment Available for >= LBC_UNSTICK_GAP s but an ALB Ingress has no address
#                                                              -> B
#   anything else (unreadable hub, pods still starting)        -> no action
#
# Bounds: at most LBC_UNSTICK_MAX actions (default 2), at least LBC_UNSTICK_GAP seconds apart
# (default 180), never before LBC_UNSTICK_AFTER seconds (default 480). Time is the caller's
# own wait counter, passed as the first argument, so the tests need no real clock.
# State (action count, time of the last action) lives in LBC_UNSTICK_STATE; the caller removes
# it when its wait starts. Each evaluation prints one line:
#   lbc-unstick: <diagnosis> -> <action|none> (<rc|->)
#
# Never fails: a hub that cannot be read, or an action that fails, only logs. The ALB wait
# keeps its own deadline. Generic: reads only the hub it is given, no consumer git host.
#
# Usage:  lbc-unstick.sh <seconds-waited>
# Env:    HUB_CLUSTER_NAME (required), AWS_REGION (required), LBC_UNSTICK_AFTER=480,
#         LBC_UNSTICK_GAP=180, LBC_UNSTICK_MAX=2, LBC_UNSTICK_STATE=/tmp/lbc-unstick.state,
#         LBC_NAMESPACE=kube-system
set -euo pipefail

WAITED="${1:?usage: lbc-unstick.sh <seconds-waited>}"
HUB="${HUB_CLUSTER_NAME:?HUB_CLUSTER_NAME required}"
REGION="${AWS_REGION:?AWS_REGION required}"
AFTER="${LBC_UNSTICK_AFTER:-480}"
GAP="${LBC_UNSTICK_GAP:-180}"
MAX="${LBC_UNSTICK_MAX:-2}"
STATE="${LBC_UNSTICK_STATE:-/tmp/lbc-unstick.state}"
NS="${LBC_NAMESPACE:-kube-system}"
SA=aws-load-balancer-controller-sa
DEP=aws-load-balancer-controller
APP="aws-load-balancer-controller-${HUB}"

say() { printf 'lbc-unstick: %s\n' "$1"; }

[ "$WAITED" -ge "$AFTER" ] || exit 0

COUNT=0; LAST=0
if [ -s "$STATE" ]; then read -r COUNT LAST < "$STATE" || true; fi
[ "$COUNT" -lt "$MAX" ] || exit 0
if [ "$COUNT" -gt 0 ] && [ "$((WAITED - LAST))" -lt "$GAP" ]; then exit 0; fi

KC=$(mktemp)
trap 'rm -f "$KC"' EXIT
if ! aws eks update-kubeconfig --name "$HUB" --region "$REGION" --kubeconfig "$KC" >/dev/null 2>&1; then
  say "no-kubeconfig -> none (-)"; exit 0
fi
export KUBECONFIG="$KC"
K="kubectl --request-timeout=20s"

# Diagnosis. `|| DIAG=unreadable` keeps a throttled/unreachable API server from aborting.
DIAG=""
SA_OUT=$($K -n "$NS" get sa "$SA" -o name --ignore-not-found 2>/dev/null) || DIAG=unreadable
DEP_JSON=""
if [ -z "$DIAG" ]; then
  DEP_JSON=$($K -n "$NS" get deploy "$DEP" -o json --ignore-not-found 2>/dev/null) || DIAG=unreadable
fi
if [ -z "$DIAG" ]; then
  if [ -z "$SA_OUT" ] || [ -z "$DEP_JSON" ]; then
    DIAG=missing
  else
    AVAIL=$(printf '%s' "$DEP_JSON" | jq -r '.status.availableReplicas // 0')
    if [ "$AVAIL" = 0 ]; then
      RS_JSON=$($K -n "$NS" get rs -l "app.kubernetes.io/name=$DEP" -o json 2>/dev/null) || RS_JSON=""
      [ -n "$RS_JSON" ] || RS_JSON='{}'
      FAILED=$(printf '%s' "$RS_JSON" | jq -r '
        [.items // [] | sort_by(.metadata.creationTimestamp) | .[-1].status.conditions // [] | .[]
         | select(.type == "ReplicaFailure" and .status == "True")] | length' 2>/dev/null) || FAILED=0
      if [ "${FAILED:-0}" -gt 0 ]; then DIAG=rsfailed; else DIAG=starting; fi
    else
      SINCE=$(printf '%s' "$DEP_JSON" | jq -r '[.status.conditions // [] | .[] | select(.type == "Available" and .status == "True") | .lastTransitionTime][0] // ""')
      AGE=0
      if [ -n "$SINCE" ] && TS=$(date -u -d "$SINCE" +%s 2>/dev/null); then AGE=$(( $(date -u +%s) - TS )); fi
      ING_JSON=$($K get ingress -A -o json 2>/dev/null) || ING_JSON=""
      [ -n "$ING_JSON" ] || ING_JSON='{}'
      NOADDR=$(printf '%s' "$ING_JSON" | jq -r '
        [.items // [] | .[] | select(((.spec.ingressClassName // "") | test("alb"))
           and ((.status.loadBalancer.ingress // []) | length == 0))] | length' 2>/dev/null) || NOADDR=0
      if [ "$AGE" -ge "$GAP" ] && [ "${NOADDR:-0}" -gt 0 ]; then DIAG=noaddr; else DIAG=running; fi
    fi
  fi
fi

case "$DIAG" in
  missing)
    ACT="argocd-app-kick"
    set +e; OUT=$(bash "$(dirname "$0")/argocd-app-kick.sh" "$APP" 2>&1); RC=$?; set -e ;;
  rsfailed|noaddr)
    ACT="rollout-restart"
    set +e; OUT=$($K -n "$NS" rollout restart "deploy/$DEP" 2>&1); RC=$?; set -e ;;
  *)
    say "$DIAG -> none (-)"; exit 0 ;;
esac
say "$DIAG -> $ACT ($RC)"
[ -z "${OUT:-}" ] || say "  $OUT"
printf '%s %s\n' "$((COUNT + 1))" "$WAITED" > "$STATE" 2>/dev/null || true
exit 0
