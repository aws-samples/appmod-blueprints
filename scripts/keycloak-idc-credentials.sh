#!/bin/bash
# keycloak-idc-credentials.sh
# Standalone version of the CDK Lambda: keycloak-idc-integration-credentials-lambda.py
#
# What the original Lambda does:
#   1. Assumes a shared IAM role (with AdministratorAccess)
#   2. Stores the temporary credentials as JSON in SSM Parameter Store
#   3. These credentials are then used by Keycloak's IDC integration to manage
#      Identity Center resources (create/sync users/groups between IDC and Keycloak)
#
# Usage: ./keycloak-idc-credentials.sh [--role-arn <arn>] [--parameter-prefix <prefix>] [--duration <seconds>]

set -euo pipefail

# Defaults from environment
AWS_REGION="${AWS_REGION:-us-west-2}"
RESOURCE_PREFIX="${RESOURCE_PREFIX:-peeks}"
ROLE_ARN="${1:-}"
PARAMETER_PREFIX="/${RESOURCE_PREFIX}/keycloak-idc-integration-credentials"
SESSION_DURATION=3600  # 1 hour (max for role chaining)

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    --role-arn) ROLE_ARN="$2"; shift 2 ;;
    --parameter-prefix) PARAMETER_PREFIX="$2"; shift 2 ;;
    --duration) SESSION_DURATION="$2"; shift 2 ;;
    --delete) DELETE=true; shift ;;
    *) shift ;;
  esac
done

# Auto-discover role if not provided
if [ -z "$ROLE_ARN" ]; then
  ROLE_ARN=$(aws iam list-roles --query "Roles[?contains(RoleName, 'SharedRole')].Arn" --output text 2>/dev/null | head -1)
  if [ -z "$ROLE_ARN" ]; then
    echo "ERROR: Could not find SharedRole. Provide --role-arn explicitly."
    exit 1
  fi
  echo "Auto-discovered role: $ROLE_ARN"
fi

# Handle delete
if [ "${DELETE:-false}" = "true" ]; then
  echo "Deleting SSM parameter: $PARAMETER_PREFIX"
  aws ssm delete-parameter --name "$PARAMETER_PREFIX" --region "$AWS_REGION" 2>/dev/null || echo "Parameter not found (already deleted)"
  exit 0
fi

echo "=== Keycloak IDC Integration Credentials ==="
echo "Role ARN:         $ROLE_ARN"
echo "Parameter:        $PARAMETER_PREFIX"
echo "Session Duration: ${SESSION_DURATION}s"
echo "Region:           $AWS_REGION"
echo ""

# Assume the role
echo "▸ Assuming role..."
CREDS=$(aws sts assume-role \
  --role-arn "$ROLE_ARN" \
  --role-session-name "KeycloakIDCIntegrationSession" \
  --duration-seconds "$SESSION_DURATION" \
  --region "$AWS_REGION" \
  --output json)

ACCESS_KEY=$(echo "$CREDS" | jq -r '.Credentials.AccessKeyId')
SECRET_KEY=$(echo "$CREDS" | jq -r '.Credentials.SecretAccessKey')
SESSION_TOKEN=$(echo "$CREDS" | jq -r '.Credentials.SessionToken')
EXPIRATION=$(echo "$CREDS" | jq -r '.Credentials.Expiration')

# Build credentials JSON (same format as the Lambda)
CREDENTIALS_JSON=$(jq -n \
  --arg ak "$ACCESS_KEY" \
  --arg sk "$SECRET_KEY" \
  --arg st "$SESSION_TOKEN" \
  --arg exp "$EXPIRATION" \
  '{AccessKeyId: $ak, SecretAccessKey: $sk, SessionToken: $st, Expiration: $exp}')

# Store in SSM Parameter Store
echo "▸ Storing credentials in SSM: $PARAMETER_PREFIX"
aws ssm put-parameter \
  --name "$PARAMETER_PREFIX" \
  --value "$CREDENTIALS_JSON" \
  --type "SecureString" \
  --overwrite \
  --description "Keycloak IDC Integration temporary credentials for $ROLE_ARN" \
  --region "$AWS_REGION" > /dev/null

echo ""
echo "✓ Credentials stored successfully"
echo "  Parameter: $PARAMETER_PREFIX"
echo "  Expires:   $EXPIRATION"
echo ""
echo "To verify: aws ssm get-parameter --name '$PARAMETER_PREFIX' --with-decryption --region $AWS_REGION --query 'Parameter.Value' --output text | jq ."
