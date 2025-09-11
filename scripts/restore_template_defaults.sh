#!/bin/bash

# Exit on error
set -e

# Source colors for output formatting
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPT_DIR/colors.sh"

print_header "Restoring Backstage Template Defaults"

# Default commit/branch to restore from
DEFAULT_RESTORE_REF="github/riv25"
RESTORE_REF="${1:-$DEFAULT_RESTORE_REF}"

# Define the template files that get modified by update_template_defaults.sh
TEMPLATE_FILES=(
    "platform/backstage/templates/eks-cluster-template/template.yaml"
    "platform/backstage/templates/create-dev-and-prod-env/template-create-dev-and-prod-env.yaml"
    "platform/backstage/templates/app-deploy/template.yaml"
    "platform/backstage/templates/app-deploy-without-repo/template.yaml"
    "platform/backstage/templates/s3-bucket/template.yaml"
    "platform/backstage/templates/s3-bucket-ack/template.yaml"
    "platform/backstage/templates/rds-cluster/template.yaml"
)

print_info "Restoring template files from: $RESTORE_REF"

# Check if the reference exists
if ! git rev-parse --verify "$RESTORE_REF" >/dev/null 2>&1; then
    print_error "Reference '$RESTORE_REF' not found. Please ensure the remote/branch exists."
    print_info "Usage: $0 [git-ref]"
    print_info "Example: $0 github/riv25"
    print_info "Example: $0 origin/main"
    exit 1
fi

# Restore each template file
restored_count=0
for file in "${TEMPLATE_FILES[@]}"; do
    if [ -f "$file" ]; then
        print_step "Restoring $file"
        if git checkout "$RESTORE_REF" -- "$file" 2>/dev/null; then
            print_success "✓ Restored $file"
            ((restored_count++))
        else
            print_warning "⚠ Could not restore $file (may not exist in $RESTORE_REF)"
        fi
    else
        print_warning "⚠ File not found: $file"
    fi
done

if [ $restored_count -gt 0 ]; then
    print_success "Successfully restored $restored_count template files from $RESTORE_REF"
    
    # Show git status
    print_info "Git status after restoration:"
    git status --porcelain | grep -E "^\s*M\s+" | while read -r line; do
        echo "  Modified: ${line#*M }"
    done
    
    print_info "To commit these changes, run:"
    echo "  git add ."
    echo "  git commit -m \"Restore template files to original state from $RESTORE_REF\""
else
    print_warning "No files were restored"
fi
