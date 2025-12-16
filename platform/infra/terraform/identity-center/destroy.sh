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

echo "✅ Identity Center destroy completed"
