#!/bin/bash

# Script to update Backstage templates from publish:gitea to publish:gitlab
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo -e "\n${BLUE}=== $1 ===${NC}\n"
}

print_header "Updating Backstage Templates from Gitea to GitLab"

# Find all template files that use publish:gitea
TEMPLATE_FILES=$(find ../platform/backstage/templates -name "*.yaml" -exec grep -l "publish:gitea" {} \;)

if [ -z "$TEMPLATE_FILES" ]; then
    print_warning "No template files found with publish:gitea action"
    exit 0
fi

print_info "Found templates to update:"
echo "$TEMPLATE_FILES" | while read -r file; do
    echo "  - $file"
done

# Update each template file
echo "$TEMPLATE_FILES" | while read -r template_file; do
    print_info "Updating $template_file"
    
    # Create backup
    cp "$template_file" "$template_file.backup"
    
    # Update the action from publish:gitea to publish:gitlab
    sed -i 's/action: publish:gitea/action: publish:gitlab/g' "$template_file"
    
    # Update the step name to reflect GitLab
    sed -i 's/name: Publishing to a gitea git repository/name: Publishing to GitLab repository/g' "$template_file"
    
    # Verify the change was made
    if grep -q "publish:gitlab" "$template_file"; then
        print_success "Updated $template_file"
    else
        print_error "Failed to update $template_file"
        # Restore backup
        mv "$template_file.backup" "$template_file"
    fi
done

print_header "Update Summary"

# Show what was changed
UPDATED_COUNT=$(find appmod-blueprints/platform/backstage/templates -name "*.yaml" -exec grep -l "publish:gitlab" {} \; | wc -l)
print_success "Updated $UPDATED_COUNT template files to use publish:gitlab"

print_info "Changes made:"
echo "  ✓ Changed 'action: publish:gitea' to 'action: publish:gitlab'"
echo "  ✓ Updated step names from 'gitea git repository' to 'GitLab repository'"

print_info "Backup files created with .backup extension"
print_info "You can remove backups with: find appmod-blueprints/platform/backstage/templates -name '*.backup' -delete"

print_success "All templates updated successfully!"