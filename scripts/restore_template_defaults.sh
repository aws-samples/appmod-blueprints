#!/bin/bash

# Exit on error
set -e

# Source all environment files in .bashrc.d
if [ -d /home/ec2-user/.bashrc.d ]; then
    for file in /home/ec2-user/.bashrc.d/*.sh; do
        if [ -f "$file" ]; then
            source "$file"
        fi
    done
fi

# Source colors for output formatting
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/colors.sh"

print_header "Restoring Backstage Template Configuration"

# Define catalog-info.yaml path
CATALOG_INFO_PATH="/home/ec2-user/environment/platform-on-eks-workshop/platform/backstage/templates/catalog-info.yaml"

if [ ! -f "$CATALOG_INFO_PATH" ]; then
    print_error "catalog-info.yaml not found at $CATALOG_INFO_PATH"
    exit 1
fi

print_step "Restoring template placeholders in catalog-info.yaml"

# Restore template placeholders in the system-info entity
yq -i '
  (select(.metadata.name == "system-info").spec.hostname) = "{{ values.gitlabDomain }}" |
  (select(.metadata.name == "system-info").spec.gituser) = "{{ values.gitUsername }}" |
  (select(.metadata.name == "system-info").spec.aws_region) = "{{ values.awsRegion }}" |
  (select(.metadata.name == "system-info").spec.aws_account_id) = "{{ values.awsAccountId }}"
' "$CATALOG_INFO_PATH"

print_success "Restored template placeholders in catalog-info.yaml"

# Stage the modified file
print_step "Staging catalog-info.yaml"
git add "$CATALOG_INFO_PATH"
print_success "Staged catalog-info.yaml"

print_success "Backstage template configuration restored to template defaults!"

print_info "Templates now use template placeholders:"
echo "  ✓ Hostname: {{ values.gitlabDomain }}"
echo "  ✓ Git User: {{ values.gitUsername }}"
echo "  ✓ AWS Region: {{ values.awsRegion }}"
echo "  ✓ AWS Account ID: {{ values.awsAccountId }}"
