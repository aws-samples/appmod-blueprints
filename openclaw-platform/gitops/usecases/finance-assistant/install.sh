#!/usr/bin/env bash
set -euo pipefail

NS=finance-assistant

# 1. LiteLLM virtual API key (budget-capped) — requires LITELLM_MASTER_KEY on host
: "${LITELLM_MASTER_KEY:?Set LITELLM_MASTER_KEY (admin key for LiteLLM proxy)}"
: "${LITELLM_URL:=http://localhost:4000}"

echo "==> Creating LiteLLM virtual key with $20/month budget"
RESPONSE=$(curl -fsS -X POST "$LITELLM_URL/key/generate" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "key_alias": "finance-assistant",
    "max_budget": 20.0,
    "budget_duration": "30d",
    "models": ["bedrock/us.anthropic.claude-sonnet-4-6-20251001-v1:0",
               "bedrock/us.anthropic.claude-opus-4-20250514-v1:0"],
    "metadata": {"owner": "finance-assistant"}
  }')
API_KEY=$(echo "$RESPONSE" | python3 -c "import sys,json;print(json.load(sys.stdin)['key'])")

echo "==> Creating namespace + secret"
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NS" create secret generic finance-litellm-key \
  --from-literal=api-key="$API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> Done. Commit the Argo Applications and ArgoCD will pick up the rest."
echo "   gitops/apps/finance-assistant.yaml already points at examples/finance-assistant."
