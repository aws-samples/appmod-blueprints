#!/usr/bin/env bash
# Renders finance-ui deployment manifest with values from `terraform output`,
# commits to the GitOps repo, and lets ArgoCD sync. Idempotent.

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
MANIFEST="$ROOT/examples/finance-assistant/web-ui/k8s/deployment.yaml"
cd "$ROOT/terraform"

ECR_URL=$(terraform output -raw finance_ui_ecr_url)
POOL_ARN=$(terraform output -raw finance_cognito_user_pool_arn)
CLIENT_ID=$(terraform output -raw finance_cognito_client_id)
DOMAIN=$(terraform output -raw finance_cognito_domain)
CERT_ARN=$(terraform output -raw wildcard_cert_arn)
TAG="${1:-latest}"

echo "==> Rendering $MANIFEST"
sed -i.bak \
  -e "s|FINANCE_UI_IMAGE_PLACEHOLDER|${ECR_URL}:${TAG}|g" \
  -e "s|COGNITO_USER_POOL_ARN_PLACEHOLDER|${POOL_ARN}|g" \
  -e "s|COGNITO_CLIENT_ID_PLACEHOLDER|${CLIENT_ID}|g" \
  -e "s|COGNITO_DOMAIN_PLACEHOLDER|${DOMAIN}|g" \
  -e "s|WILDCARD_CERT_ARN_PLACEHOLDER|${CERT_ARN}|g" \
  "$MANIFEST"
rm -f "${MANIFEST}.bak"

echo "==> Done. Review the diff, then commit + push so ArgoCD syncs."
echo "    git diff examples/finance-assistant/web-ui/k8s/deployment.yaml"
