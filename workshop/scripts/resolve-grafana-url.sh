#!/bin/sh
# resolve-grafana-url.sh: write GRAFANA_URL, the Amazon Managed Grafana (AMG) endpoint, to the
# IDE env file (~/.bashrc.d/platform.sh). Used by the workshop `setup-env` task.
#
# AMG (<prefix>-observability) is created by the hub (Crossplane) at a time that varies from run
# to run: before setup-env on some installs, minutes after it on others. setup-env runs this once
# with a short wait; if AMG is not there yet it writes the AMG console fallback and starts this
# again in the background with a long wait, so GRAFANA_URL is corrected once AMG exists. New
# shells then read the real endpoint. Nothing here writes a CloudFront /grafana path (it does
# not exist: there is no in-cluster Grafana behind the ALB).
#
# Usage: resolve-grafana-url.sh <env-file> <region> <prefix> <tries> <interval-sec>
# Exit:  0 = GRAFANA_URL written, 1 = no AMG endpoint after <tries> polls (env file untouched).
set -u
ENV_FILE="$1" REGION="$2" PREFIX="$3" TRIES="$4" INTERVAL="$5"

i=0
while [ "$i" -lt "$TRIES" ]; do
  i=$((i + 1))
  EP=""
  WS_ID=$(aws grafana list-workspaces --region "$REGION" \
    --query "workspaces[?name=='${PREFIX}-observability'].id | [0]" --output text 2>/dev/null || echo "")
  if [ -n "$WS_ID" ] && [ "$WS_ID" != "None" ]; then
    EP=$(aws grafana describe-workspace --workspace-id "$WS_ID" --region "$REGION" \
      --query 'workspace.endpoint' --output text 2>/dev/null || echo "")
  fi
  # A hostname only: the value goes into a sed replacement and an exported shell string.
  case "$EP" in ""|None|*[!A-Za-z0-9.-]*) EP="" ;; esac
  if [ -n "$EP" ]; then
    LINE="export GRAFANA_URL=\"https://${EP}\""
    if grep -q '^export GRAFANA_URL=' "$ENV_FILE" 2>/dev/null; then
      sed -i "s|^export GRAFANA_URL=.*|${LINE}|" "$ENV_FILE"
    else
      echo "$LINE" >> "$ENV_FILE"
    fi
    echo "GRAFANA_URL=https://${EP} written to ${ENV_FILE} (poll ${i}/${TRIES})"
    exit 0
  fi
  if [ "$i" -lt "$TRIES" ]; then sleep "$INTERVAL"; fi
done
echo "no AMG endpoint for ${PREFIX}-observability after ${TRIES} polls" >&2
exit 1
