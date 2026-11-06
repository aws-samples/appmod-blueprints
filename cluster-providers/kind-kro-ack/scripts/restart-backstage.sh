#!/usr/bin/env bash
# Restart Backstage after Keycloak is configured, only when it is useful, and check that
# the backend really came up. Called by `hub:restart-backstage` (install:finalize).
#
# Why the restart exists: a Backstage pod that started before the keycloak-config PostSync
# hook wrote the client secret keeps a stale OIDC client and stale keep-alive sockets.
#
# Why it is careful: a restart started while the current pod is still doing its first-boot
# database migrations used to run two pods on the same database. Both inserted a row into
# a *_knex_migrations_lock table, and from then on every start failed with MigrationLocked
# while the pod stayed Running with an empty or 503 catalog. The chart now runs Backstage
# with strategy Recreate and repairs a duplicated lock in the dedupe-migration-locks init
# container. This script adds the rest:
#   1. Skip the restart when the current pod started after Keycloak was configured: it
#      already has the fresh secret and sockets.
#   2. Otherwise wait until the current pod has finished initialising (Ready and
#      "Plugin initialization complete", or a startup failure) before restarting it.
#   3. Gate: fail when the pod logs "Backend startup failed" or "MigrationLocked", or when
#      the catalog does not serve the gate template to an authenticated request.
#   4. On a failed gate: one restart (the init container repairs the lock), then the gate
#      again, then a clear error. Nothing is hidden behind `|| true`.
#
# Backstage may not be deployed yet when this runs: install:finalize comes right after
# Keycloak is configured, and the Backstage Deployment is a late sync wave of its Argo CD
# app (seen live: the task ran at 15:23, the Deployment appeared at 15:32). So the script
# first decides whether Backstage is expected (`probe` prints the answer):
#   present   deploy/<BACKSTAGE_DEPLOY> exists
#   expected  no Deployment yet, but the Argo CD app BACKSTAGE_APP exists or the hub
#             cluster secret HUB_CLUSTER_SECRET carries enable_backstage=true
#   absent    neither: Backstage is not installed
# When expected, it waits up to WAIT_DEPLOY_TIMEOUT for the Deployment and a scheduled pod,
# then runs steps 1-4. When absent, it exits 3 (skipped), so the caller never reports a
# healthy Backstage that was not checked.
#
# Usage: restart-backstage.sh          restart if needed + gate (exit 0 healthy, 1 unhealthy
#                                      or never deployed, 3 not installed)
#        restart-backstage.sh probe    print present | expected | absent, exit 0
#
# Environment (all optional except KUBECONFIG, which kubectl reads):
#   BACKSTAGE_NS (backstage), BACKSTAGE_DEPLOY (backstage), BACKSTAGE_BASE_PATH (/backstage)
#   KEYCLOAK_APP          Argo CD Application of Keycloak (keycloak-<hub>)
#   BACKSTAGE_APP         Argo CD Application of Backstage (backstage-<hub>); empty = not used
#   HUB_CLUSTER_SECRET    Argo CD cluster secret of the hub (<hub>); empty = not used
#   ARGOCD_NS             (argocd)
#   WAIT_DEPLOY_TIMEOUT   seconds to wait for an expected Deployment and its pod (900)
#   GATE_TEMPLATE         catalog template the gate requires (cicd-pipeline-gitops); empty
#                         = only require the catalog to answer 200
#   WAIT_INIT_TIMEOUT     seconds to wait for the current pod to finish init (600)
#   ROLLOUT_TIMEOUT       seconds for `kubectl rollout status` (420)
#   GATE_TIMEOUT          seconds for the gate (600)
#   POLL_INTERVAL         seconds between checks (10)
set -u

NS=${BACKSTAGE_NS:-backstage}
DEPLOY=${BACKSTAGE_DEPLOY:-backstage}
BASE_PATH=${BACKSTAGE_BASE_PATH:-/backstage}
KEYCLOAK_APP=${KEYCLOAK_APP:-}
BACKSTAGE_APP=${BACKSTAGE_APP:-}
HUB_CLUSTER_SECRET=${HUB_CLUSTER_SECRET:-}
ARGOCD_NS=${ARGOCD_NS:-argocd}
WAIT_DEPLOY_TIMEOUT=${WAIT_DEPLOY_TIMEOUT:-900}
GATE_TEMPLATE=${GATE_TEMPLATE-cicd-pipeline-gitops}
WAIT_INIT_TIMEOUT=${WAIT_INIT_TIMEOUT:-600}
ROLLOUT_TIMEOUT=${ROLLOUT_TIMEOUT:-420}
GATE_TIMEOUT=${GATE_TIMEOUT:-600}
POLL_INTERVAL=${POLL_INTERVAL:-10}
FAIL_PATTERN='Backend startup failed|MigrationLocked'

info() { printf '  %s\n' "$*"; }
err() { printf 'ERROR: %s\n' "$*" >&2; }

if [ -n "$GATE_TEMPLATE" ]; then
  CATALOG_PATH="$BASE_PATH/api/catalog/entities/by-name/template/default/$GATE_TEMPLATE"
else
  CATALOG_PATH="$BASE_PATH/api/catalog/entities/by-query?limit=1"
fi

# Newest Backstage pod that is not being deleted, as "<name> <startTime>".
current_pod() {
  kubectl -n "$NS" get pods -l "app=$DEPLOY" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"|"}{.metadata.deletionTimestamp}{"|"}{.status.startTime}{"\n"}{end}' 2>/dev/null \
    | awk -F'|' '$1 != "" && $2 == "" { print $3, $1 }' | sort | tail -n 1 | awk '{ print $2, $1 }'
}

pod_ready() {
  [ "$(kubectl -n "$NS" get pod "$1" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)" = "True" ]
}

# starting | initialized | failed, from the backend container's log.
pod_init_state() {
  local logs
  logs=$(kubectl -n "$NS" logs "$1" -c backstage 2>/dev/null)
  if printf '%s' "$logs" | grep -Eq "$FAIL_PATTERN"; then
    echo failed
  elif printf '%s' "$logs" | grep -q 'Plugin initialization complete'; then
    echo initialized
  else
    echo starting
  fi
}

failure_lines() {
  kubectl -n "$NS" logs "$1" -c backstage 2>/dev/null | grep -E "$FAIL_PATTERN" | head -n 3
}

# HTTP status of an authenticated catalog read, from inside the pod. The static
# externalAccess token (BACKEND_SECRET, backend.auth.externalAccess in app-config) is in
# the container's environment, so nothing secret leaves the pod. An unauthenticated 401
# does not prove the catalog works, which is why the request carries the token.
catalog_status() {
  kubectl -n "$NS" exec "$1" -c backstage -- node -e '
const http = require("http");
const req = http.get({ host: "127.0.0.1", port: 7007, path: process.argv[1], timeout: 10000,
  headers: { Authorization: "Bearer " + (process.env.BACKEND_SECRET || "") } },
  (res) => { console.log(res.statusCode); res.resume(); });
req.on("timeout", () => req.destroy(new Error("timeout")));
req.on("error", () => console.log("000"));' "$CATALOG_PATH" 2>/dev/null | tail -n 1
}

ensure_recreate() {
  local strategy
  strategy=$(kubectl -n "$NS" get deploy "$DEPLOY" -o jsonpath='{.spec.strategy.type}' 2>/dev/null)
  if [ "$strategy" != "Recreate" ]; then
    # The chart sets Recreate; a live Deployment without it comes from an older chart
    # revision. Two overlapping pods are exactly what breaks the migration lock, so align
    # the live object with the chart before restarting.
    info "Deployment strategy is '${strategy:-?}', setting Recreate so two pods never share the database"
    kubectl -n "$NS" patch deploy "$DEPLOY" --type=merge \
      -p '{"spec":{"strategy":{"type":"Recreate","rollingUpdate":null}}}' >/dev/null || return 1
  fi
}

restart() {
  ensure_recreate || { err "could not set strategy Recreate on deploy/$DEPLOY"; return 1; }
  kubectl -n "$NS" rollout restart deploy "$DEPLOY" >/dev/null || { err "rollout restart deploy/$DEPLOY failed"; return 1; }
  if ! kubectl -n "$NS" rollout status deploy "$DEPLOY" --timeout="${ROLLOUT_TIMEOUT}s" >/dev/null; then
    info "rollout status did not finish within ${ROLLOUT_TIMEOUT}s; the gate decides"
  fi
}

# Wait until the current pod has finished initialising (or failed) so a restart never
# interrupts first-boot migrations.
wait_current_init() {
  local pod=$1 waited=0 state
  while [ "$waited" -lt "$WAIT_INIT_TIMEOUT" ]; do
    state=$(pod_init_state "$pod")
    if [ "$state" = failed ]; then
      info "current pod $pod failed to start: $(failure_lines "$pod" | head -n 1)"
      return 0
    fi
    if [ "$state" = initialized ] && pod_ready "$pod"; then
      info "current pod $pod is Ready and finished plugin initialization"
      return 0
    fi
    sleep "$POLL_INTERVAL"; waited=$((waited + POLL_INTERVAL))
  done
  info "current pod $pod still initialising after ${WAIT_INIT_TIMEOUT}s; restarting anyway"
}

GATE_REASON=""
gate() {
  local waited=0 line pod state code=""
  GATE_REASON="no Backstage pod"
  while :; do
    line=$(current_pod)
    pod=${line%% *}
    if [ -n "$pod" ]; then
      state=$(pod_init_state "$pod")
      if [ "$state" = failed ]; then
        GATE_REASON="pod $pod logged: $(failure_lines "$pod" | head -n 1)"
        return 1
      fi
      if pod_ready "$pod"; then
        code=$(catalog_status "$pod")
        if [ "$code" = 200 ]; then
          info "gate passed: pod $pod Ready, catalog serves ${GATE_TEMPLATE:-entities} (authenticated, HTTP 200)"
          return 0
        fi
        GATE_REASON="pod $pod Ready but the authenticated catalog read of $CATALOG_PATH returned HTTP ${code:-none}"
      else
        GATE_REASON="pod $pod not Ready (init state: $state)"
      fi
    fi
    [ "$waited" -ge "$GATE_TIMEOUT" ] && return 1
    sleep "$POLL_INTERVAL"; waited=$((waited + POLL_INTERVAL))
  done
}

report_dedupe() {
  local pod out
  pod=$(current_pod); pod=${pod%% *}
  [ -n "$pod" ] || return 0
  out=$(kubectl -n "$NS" logs "$pod" -c dedupe-migration-locks 2>/dev/null | grep 'dedupe-migration-locks' | tail -n 5)
  [ -n "$out" ] && printf '%s\n' "$out" | sed 's/^/  /'
  return 0
}

deploy_exists() {
  kubectl -n "$NS" get deploy "$DEPLOY" >/dev/null 2>&1
}

# present | expected | absent (see the header).
backstage_state() {
  if deploy_exists; then
    echo present; return
  fi
  if [ -n "$BACKSTAGE_APP" ] &&
     kubectl -n "$ARGOCD_NS" get application.argoproj.io "$BACKSTAGE_APP" >/dev/null 2>&1; then
    echo expected; return
  fi
  if [ -n "$HUB_CLUSTER_SECRET" ] &&
     [ "$(kubectl -n "$ARGOCD_NS" get secret "$HUB_CLUSTER_SECRET" \
          -o jsonpath='{.metadata.labels.enable_backstage}' 2>/dev/null)" = "true" ]; then
    echo expected; return
  fi
  echo absent
}

# Wait for the Deployment and a scheduled pod (one with a startTime), so the restart
# decision below compares a real pod start with the Keycloak config time.
wait_deployed() {
  local waited=0 line
  while [ "$waited" -lt "$WAIT_DEPLOY_TIMEOUT" ]; do
    if deploy_exists; then
      line=$(current_pod)
      # current_pod prints " <name>" (empty first field) for a pod without a startTime.
      if [ -n "${line%% *}" ]; then
        info "deploy/$DEPLOY and pod ${line%% *} present after ${waited}s"
        return 0
      fi
    fi
    if [ $((waited % 60)) -eq 0 ]; then
      info "[${waited}s] waiting for deploy/$DEPLOY and its pod in namespace $NS (up to ${WAIT_DEPLOY_TIMEOUT}s)"
    fi
    sleep "$POLL_INTERVAL"; waited=$((waited + POLL_INTERVAL))
  done
  return 1
}

# ── main ────────────────────────────────────────────────────────────────────────
STATE=$(backstage_state)
if [ "${1:-}" = probe ]; then
  echo "$STATE"
  exit 0
fi
case "$STATE" in
  absent)
    info "Backstage not installed: skipped (no deploy/$DEPLOY in $NS${BACKSTAGE_APP:+, no Argo CD app $BACKSTAGE_APP}${HUB_CLUSTER_SECRET:+, hub label enable_backstage is not true})"
    exit 3 ;;
  expected)
    info "Backstage is expected but deploy/$DEPLOY does not exist yet: waiting for it"
    if ! wait_deployed; then
      err "deploy/$DEPLOY or its pod did not appear within ${WAIT_DEPLOY_TIMEOUT}s; Backstage was not checked"
      err "inspect: kubectl -n $ARGOCD_NS get application.argoproj.io ${BACKSTAGE_APP:-<backstage app>}"
      exit 1
    fi ;;
esac

LINE=$(current_pod)
POD=${LINE%% *}
POD_START=${LINE#* }
KC_DONE=""
if [ -n "$KEYCLOAK_APP" ]; then
  KC_DONE=$(kubectl -n "$ARGOCD_NS" get application.argoproj.io "$KEYCLOAK_APP" \
    -o jsonpath='{.status.operationState.finishedAt}' 2>/dev/null)
fi

if [ -n "$POD" ] && [ -n "$KC_DONE" ] && [[ "$POD_START" > "$KC_DONE" ]]; then
  info "pod $POD started at $POD_START, after Keycloak was configured ($KC_DONE): restart not needed"
else
  if [ -n "$POD" ]; then
    info "pod $POD started at ${POD_START:-?}, Keycloak configured at ${KC_DONE:-unknown}: restart needed"
    wait_current_init "$POD"
  fi
  info "restarting deploy/$DEPLOY (strategy Recreate)"
  restart || exit 1
fi

if gate; then
  exit 0
fi
info "Backstage gate failed: $GATE_REASON"
info "repairing: one restart (the dedupe-migration-locks init container repairs a duplicated lock)"
restart || exit 1
report_dedupe
if gate; then
  info "Backstage recovered after the repair restart"
  exit 0
fi
err "Backstage is not healthy after one repair restart: $GATE_REASON"
err "inspect: kubectl -n $NS logs deploy/$DEPLOY -c backstage | grep -E '$FAIL_PATTERN'"
err "         kubectl -n $NS logs deploy/$DEPLOY -c dedupe-migration-locks"
exit 1
