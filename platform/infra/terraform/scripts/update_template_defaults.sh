#!/bin/bash

# Exit on error
set -e

print_header "Updating Backstage Template Configuration"

# Define catalog-info.yaml path
CATALOG_INFO_PATH="${GIT_ROOT_PATH}/platform/backstage/templates/catalog-info.yaml"

print_info "Using the following values for catalog-info.yaml update:"
echo "  Account ID: $AWS_ACCOUNT_ID"
echo "  AWS Region: $AWS_REGION"
echo "  GitLab Domain: $GITLAB_DOMAIN"
echo "  Git Username: $GIT_USERNAME"

print_step "Updating catalog-info.yaml with environment-specific values"

# Create backup before modifying
BACKUP_PATH="${CATALOG_INFO_PATH}.backup.$(date +%Y%m%d_%H%M%S)"
cp "$CATALOG_INFO_PATH" "$BACKUP_PATH"
print_info "Created backup: $BACKUP_PATH"

# Update the system-info entity in catalog-info.yaml
yq -i '
  (select(.metadata.name == "system-info").spec.hostname) = "'$GITLAB_DOMAIN'" |
  (select(.metadata.name == "system-info").spec.gituser) = "'$GIT_USERNAME'" |
  (select(.metadata.name == "system-info").spec.aws_region) = "'$AWS_REGION'" |
  (select(.metadata.name == "system-info").spec.aws_account_id) = "'$AWS_ACCOUNT_ID'"
' "$CATALOG_INFO_PATH"

print_success "Updated catalog-info.yaml with environment values"

# Stage the modified file
print_step "Staging catalog-info.yaml"
git add "$CATALOG_INFO_PATH"
print_success "Staged catalog-info.yaml"

print_success "Backstage template configuration updated!"

print_info "Templates can now reference these values using:"
echo "  ✓ Hostname: \${{ steps['fetchSystem'].output.entity.spec.hostname }}"
echo "  ✓ Git User: \${{ steps['fetchSystem'].output.entity.spec.gituser }}"
echo "  ✓ AWS Region: \${{ steps['fetchSystem'].output.entity.spec.aws_region }}"
echo "  ✓ AWS Account ID: \${{ steps['fetchSystem'].output.entity.spec.aws_account_id }}"

print_info "Other templates should use the fetchSystem step to retrieve configuration from catalog-info.yaml"
