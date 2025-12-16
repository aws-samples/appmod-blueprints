#!/bin/bash
set -e

# Get the directory of this script and source common functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo "🚀 Deploying Identity Center prerequisites..."

# Check if IDC instance exists, create if needed
echo "🔍 Checking for existing Identity Center instance..."
IDC_INSTANCES=$(aws sso-admin list-instances --query 'Instances[0].InstanceArn' --output text 2>/dev/null || echo "None")

if [[ "$IDC_INSTANCES" == "None" ]]; then
  echo "📝 No Identity Center instance found. Creating one..."
  aws sso-admin create-instance --name "PEEKS-WORKSHOP" || echo "⚠️  Instance creation may be in progress or require manual setup"
  sleep 10
fi

# Initialize and apply
terraform init -backend-config="bucket=${TFSTATE_BUCKET_NAME}" -backend-config="region=${AWS_REGION}"
terraform plan -var="create_test_user=true"
terraform apply -var="create_test_user=true" -auto-approve

echo "✅ Identity Center setup complete!"

# Export outputs for use by cluster module
echo ""
echo "📋 Identity Center Configuration:"
INSTANCE_ARN=$(terraform output -raw instance_arn 2>/dev/null || echo "")
ADMIN_GROUP=$(terraform output -raw admin_group_id 2>/dev/null || echo "")
DEV_GROUP=$(terraform output -raw developer_group_id 2>/dev/null || echo "")

if [[ -n "$INSTANCE_ARN" && "$INSTANCE_ARN" != "null" ]]; then
  echo "export TF_VAR_identity_center_instance_arn=\"$INSTANCE_ARN\""
  echo "export TF_VAR_identity_center_admin_group_id=\"$ADMIN_GROUP\""
  echo "export TF_VAR_identity_center_developer_group_id=\"$DEV_GROUP\""
  echo ""
  echo "💡 Copy and run the above export commands before deploying clusters."
else
  echo "⚠️  No Identity Center instance available. EKS Capabilities will be created without SSO."
fi
