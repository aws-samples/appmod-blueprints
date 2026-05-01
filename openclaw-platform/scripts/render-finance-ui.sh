#!/usr/bin/env bash
# Renders finance-ui deployment manifest with values from `terraform output`,
# commits to the GitOps repo, and lets ArgoCD sync. Idempotent.

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
MANIFEST="$ROOT/gitops/usecases/finance-assistant/web-ui/k8s/deployment.yaml"
EXTDNS_VALUES="$ROOT/gitops/helm/external-dns/values.yaml"
cd "$ROOT/infra/terraform"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URL=$(terraform output -raw finance_ui_ecr_url)
CLIENT_ID=$(terraform output -raw finance_cognito_client_id)
POOL_ID=$(terraform output -raw finance_cognito_user_pool_id)
DOMAIN=$(terraform output -raw finance_cognito_domain)
CERT_ARN=$(terraform output -raw wildcard_cert_arn)
HOST=$(terraform output -raw finance_ui_host)
ZONE_ID=$(terraform output -raw route53_zone_id)
ZONE_NAME=$(terraform output -raw route53_zone_name)
TAG="${1:-latest}"

echo "==> Rendering $MANIFEST"
sed -i.bak \
  -e "s|__ACCOUNT_ID__|${ACCOUNT_ID}|g" \
  -e "s|__COGNITO_USER_POOL_ID__|${POOL_ID}|g" \
  -e "s|__COGNITO_CLIENT_ID__|${CLIENT_ID}|g" \
  -e "s|__COGNITO_DOMAIN_PREFIX__|${DOMAIN}|g" \
  -e "s|__ACM_CERTIFICATE_ARN__|${CERT_ARN}|g" \
  -e "s|__FINANCE_UI_HOST__|${HOST}|g" \
  "$MANIFEST"
rm -f "${MANIFEST}.bak"

echo "==> Rendering $EXTDNS_VALUES"
sed -i.bak \
  -e "s|__ROUTE53_ZONE_ID__|${ZONE_ID}|g" \
  -e "s|__ROUTE53_ZONE_NAME__|${ZONE_NAME}|g" \
  "$EXTDNS_VALUES"
rm -f "${EXTDNS_VALUES}.bak"

echo "==> Done. Review the diffs, then commit + push so ArgoCD syncs."
echo "    git diff openclaw-platform/gitops/"
