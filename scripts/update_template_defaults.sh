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

print_header "Updating Backstage Template Configuration"

# Define catalog-info.yaml path
CATALOG_INFO_PATH="/home/ec2-user/environment/platform-on-eks-workshop/platform/backstage/templates/catalog-info.yaml"

# Get environment-specific values
GITLAB_DOMAIN=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].DomainName, 'gitlab')].DomainName | [0]" --output text)

# Try to get GIT_USERNAME from environment or secret
if [ -z "$GIT_USERNAME" ]; then
    GIT_USERNAME=$(kubectl get secret git-credentials -n argocd -o jsonpath='{.data.GIT_USERNAME}' 2>/dev/null | base64 --decode 2>/dev/null || echo "user1")
fi

# Check if required environment variables are set
if [ -z "$AWS_ACCOUNT_ID" ]; then
  print_error "AWS_ACCOUNT_ID environment variable is not set"
  exit 1
fi

if [ -z "$AWS_REGION" ]; then
  print_error "AWS_REGION environment variable is not set"
  exit 1
fi

if [ ! -f "$CATALOG_INFO_PATH" ]; then
    print_error "catalog-info.yaml not found at $CATALOG_INFO_PATH"
    exit 1
fi

print_info "Using the following values for catalog-info.yaml update:"
echo "  Account ID: $AWS_ACCOUNT_ID"
echo "  AWS Region: $AWS_REGION"
echo "  GitLab Domain: $GITLAB_DOMAIN"
echo "  ArgoCD URL: $ARGOCD_URL"
echo "  Git Username: $GIT_USERNAME"

print_step "Updating catalog-info.yaml with environment-specific values"

# Create backup before modifying
BACKUP_PATH="${CATALOG_INFO_PATH}.backup.$(date +%Y%m%d_%H%M%S)"
cp "$CATALOG_INFO_PATH" "$BACKUP_PATH"
print_info "Created backup: $BACKUP_PATH"

# Update the system-info entity in catalog-info.yaml
yq -i '
  (select(.metadata.name == "system-info").spec.gitlab_hostname) = "'$GITLAB_DOMAIN'" |
  (select(.metadata.name == "system-info").spec.argocd_hostname) = "'${ARGOCD_URL#https://}'" |
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
echo "  ✓ GitLab Hostname: \${{ steps['fetchSystem'].output.entity.spec.gitlab_hostname }}"
echo "  ✓ ArgoCD Hostname: \${{ steps['fetchSystem'].output.entity.spec.argocd_hostname }}"
echo "  ✓ Git User: \${{ steps['fetchSystem'].output.entity.spec.gituser }}"
echo "  ✓ AWS Region: \${{ steps['fetchSystem'].output.entity.spec.aws_region }}"
echo "  ✓ AWS Account ID: \${{ steps['fetchSystem'].output.entity.spec.aws_account_id }}"

print_info "Other templates should use the fetchSystem step to retrieve configuration from catalog-info.yaml"
