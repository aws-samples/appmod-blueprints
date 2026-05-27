#!/bin/bash
# argocd-refresh-token — Retrieve ArgoCD auth token via IDC SSO (browser automation)
# Usage: source scripts/argocd-refresh-token.sh
#   Exports ARGOCD_AUTH_TOKEN, ARGOCD_SERVER, ARGOCD_OPTS

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
AUTOMATION_SCRIPT="$REPO_ROOT/platform/infra/terraform/scripts/argocd_token_automation.py"

CLUSTER_NAME="${RESOURCE_PREFIX:-peeks}-hub"
USER_PASSWORD="${IDE_PASSWORD:-$(aws secretsmanager get-secret-value --secret-id ${CLUSTER_NAME}/keycloak --region ${AWS_DEFAULT_REGION:-us-west-2} --query 'SecretString' --output text 2>/dev/null | jq -r '.user_password' 2>/dev/null)}"

SERVER_URL=$(aws eks describe-capability \
  --cluster-name "$CLUSTER_NAME" \
  --capability-name argocd \
  --region "${AWS_DEFAULT_REGION:-us-west-2}" \
  --query 'capability.configuration.argoCd.serverUrl' \
  --output text 2>/dev/null)

if [[ -z "$SERVER_URL" || "$SERVER_URL" == "None" ]]; then
  echo "ERROR: Could not get ArgoCD server URL" >&2
  exit 1
fi

echo "Retrieving ArgoCD token via SSO (this may take ~30s)..." >&2
TOKEN=$(python3 "$AUTOMATION_SCRIPT" \
  --url "$SERVER_URL" \
  --username "user1" \
  --password "$USER_PASSWORD" \
  --output token 2>/tmp/argocd-token-debug.log)

if [[ -z "$TOKEN" || "$TOKEN" == "Failed to retrieve token" ]]; then
  echo "ERROR: Failed to retrieve ArgoCD token. Debug log:" >&2
  cat /tmp/argocd-token-debug.log >&2
  exit 1
fi

export ARGOCD_AUTH_TOKEN="$TOKEN"
export ARGOCD_SERVER=$(echo "$SERVER_URL" | sed 's|https://||;s|/.*||')
export ARGOCD_OPTS="--grpc-web"

# Persist to platform.sh so new shells pick up the refreshed token
PLATFORM_SH="$HOME/.bashrc.d/platform.sh"
if [[ -f "$PLATFORM_SH" ]]; then
  sed -i '/^export ARGOCD_AUTH_TOKEN=/d' "$PLATFORM_SH"
  sed -i '/^export ARGOCD_SERVER=/d' "$PLATFORM_SH"
  sed -i '/^export ARGOCD_OPTS=/d' "$PLATFORM_SH"
  echo "export ARGOCD_AUTH_TOKEN=\"$ARGOCD_AUTH_TOKEN\"" >> "$PLATFORM_SH"
  echo "export ARGOCD_SERVER=\"$ARGOCD_SERVER\"" >> "$PLATFORM_SH"
  echo "export ARGOCD_OPTS=\"$ARGOCD_OPTS\"" >> "$PLATFORM_SH"
fi

echo "✓ ArgoCD token refreshed"
echo "  Server: $ARGOCD_SERVER"
echo "  Run: source ~/.bashrc.d/platform.sh"
