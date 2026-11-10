#!/usr/bin/env bash
# Start a fresh Argo CD sync of one Application, without the argocd CLI.
#
# Used by hub:settle's once-only crossplane-base remediation (kind-kro-ack) to unstick an
# app that is parked in Argo CD's sync-retry backoff. On a fresh hub the API server
# throttles hard during the first big sync (HTTP 429), so one create can fail and the sync
# with it. An app with no per-addon syncPolicy inherits the default retry (backoff 5s x2,
# maxDuration 10m), which can park its next attempt up to 10 min away; crossplane-base is
# such an app. Apps whose registry entry caps maxDuration lower (the load balancer
# controller: 1m) are not parked by the backoff, so hub:settle does not kick them on a
# timer; scripts/lbc-unstick.sh does reuse this script, once, when the LBC Application or
# its Deployment is still missing late in the ALB wait.
#
# Why a plain `.operation` patch is not enough: while an operation is in progress
# (status.operationState.phase=Running) the controller resumes the EXISTING operation state
# and only honours its retry timer (argo-cd controller/appcontroller.go,
# processRequestedAppOperation: isOperationInProgress -> "Skipping retrying in-progress
# operation"). A new `.operation` is read only when no operation is in progress. So when the
# app is in retry backoff (phase Running AND finishedAt set: the last attempt finished and
# failed, the next one is scheduled) this clears status.operationState in the same patch,
# which makes the controller initialise the new operation right away.
#
# The new operation carries the app's own spec.syncPolicy.syncOptions and retry (Argo CD
# reads both from the operation, not from the spec), so the sync behaves as the auto-sync
# would.
#
# Usage:  KUBECONFIG=<hub kubeconfig> argocd-app-kick.sh <application> [namespace]
# Prints one line saying what it did.
# Exit:   0 kicked · 3 not needed (Healthy, or an attempt is running now) · 1 read error
set -uo pipefail

APP="${1:?usage: argocd-app-kick.sh <application> [namespace]}"
NS="${2:-argocd}"

J=$(kubectl get applications.argoproj.io "$APP" -n "$NS" -o json 2>/dev/null) || {
  echo "kick $APP: cannot read the Application (not created yet?)"; exit 1; }

HEALTH=$(printf '%s' "$J" | jq -r '.status.health.status // "Unknown"')
PHASE=$(printf '%s' "$J" | jq -r '.status.operationState.phase // ""')
FIN=$(printf '%s' "$J" | jq -r '.status.operationState.finishedAt // ""')

if [ "$HEALTH" = "Healthy" ]; then
  echo "kick $APP: Healthy, nothing to do"; exit 3
fi
if [ "$PHASE" = "Running" ] && [ -z "$FIN" ]; then
  echo "kick $APP: a sync attempt is running now (health=$HEALTH), not interrupting it"; exit 3
fi

OP=$(printf '%s' "$J" | jq -c '
  . as $a
  | {initiatedBy: {username: "admin"}, sync: {revision: "HEAD"}}
  | (if (($a.spec.syncPolicy.syncOptions // []) | length) > 0
       then .sync.syncOptions = $a.spec.syncPolicy.syncOptions else . end)
  | (if $a.spec.syncPolicy.retry then .retry = $a.spec.syncPolicy.retry else . end)
' 2>/dev/null) || OP=""
[ -n "$OP" ] || OP='{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}'

if [ "$PHASE" = "Running" ]; then
  # Retry backoff: drop the parked operation state so the new operation starts now.
  BODY=$(jq -cn --argjson op "$OP" '{operation: $op, status: {operationState: null}}')
  WHY="in retry backoff since $FIN"
else
  BODY=$(jq -cn --argjson op "$OP" '{operation: $op}')
  WHY="last operation ${PHASE:-none}"
fi
if kubectl patch applications.argoproj.io "$APP" -n "$NS" --type merge -p "$BODY" >/dev/null 2>&1; then
  echo "kick $APP: started a fresh sync (health=$HEALTH, $WHY)"; exit 0
fi
echo "kick $APP: patch failed (health=$HEALTH, $WHY)"; exit 1
