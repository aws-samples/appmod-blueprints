#!/bin/bash
set -e

# Get the directory of this script and source common functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

echo "🧹 Destroying Identity Center resources..."

# Change to the identity-center directory
cd "${SCRIPT_DIR}"

# Run terraform destroy
if [ -f "terraform.tfstate" ] || [ -d ".terraform" ]; then
    echo "🔄 Running terraform destroy..."
    terraform destroy -auto-approve || echo "⚠️  Some resources may require manual cleanup"
else
    echo "ℹ️  No terraform state found, skipping destroy"
fi

# Delete IDC instance created by CLI
echo "🔍 Checking for IDC instances to delete..."
IDC_INSTANCES=$(aws sso-admin list-instances --query 'Instances[?Name==`PEEKS-WORKSHOP`].InstanceArn' --output text 2>/dev/null || echo "")

if [[ -n "$IDC_INSTANCES" && "$IDC_INSTANCES" != "None" ]]; then
    echo "🗑️  Deleting IDC instance..."
    for instance_arn in $IDC_INSTANCES; do
        aws sso-admin delete-instance --instance-arn "$instance_arn" || echo "⚠️  Could not delete IDC instance $instance_arn"
    done
else
    echo "ℹ️  No IDC instances found to delete"
fi

echo "✅ Identity Center destroy completed"
